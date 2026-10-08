# 302. The matters pass records what it decides, and a page write refuses what its story does not hold

- Status: Proposed
- Date: 2026-10-08
- Scope: [M42](https://github.com/leonapivato/ai-assistant/milestone/9): what the matters pass records of each flag it decides, and what a story's page write refuses ([#2761](https://github.com/leonapivato/ai-assistant/issues/2761)), and which route-table row ADR-0300's story commands take.
- Dependency: ADR-0300, whose §3 [#2750](https://github.com/leonapivato/ai-assistant/pull/2750) and §5 [#2758](https://github.com/leonapivato/ai-assistant/pull/2758) implemented; ADR-0289, implemented.
- Authorization: on 2026-10-08 the owner ruled, choosing option 2 of the two the dispatcher put, that the matters pass records each decision in the story's change log, a decision to leave the stories as they are included, and that a decided flag is revisited only when something new suggests it. The same day the dispatcher ruled #2761 (the refusal belongs inside `StoryStore.write_page`) and assigned 0302, and later added the classification of ADR-0300's four story commands in ADR-0298 §5's route table to its scope. That authorizes drafting and numbering, not ratification or implementation.
- **Changes a `core` surface.** `StoryStore` gains an operation and a keyword on five, and `StoryChange`, `StoryLogLine`, `StoryRefusalReason`, `StoryRefusal`, `StoryPageRefusalReason` and `StoryPageRefusal` change (§§3, 4 and 7 below): a Protocol change under golden rule 5, merged ratified before anything implements it.
- **Partially supersedes** [ADR-0300](0300-a-story-keeps-a-page-of-notes-and-where-its-matter-stands-is-worked-out-from-records.md) — **four scopes, each in the addition alone.** **§3:10's page write**: it is also refused where it rests on, or takes in, what its story does not hold (§7 below). **§5:2's reads**: a tidy-up also reads the decisions recorded on its story's change log (§6 below). **§5:6's instruction**: it also states when a decided flag is raised again (§6 below). **§9:3's matters pass**: it records each decision in the change log, decides each flag once, and is shown the decisions already recorded (§§3–5 below). Every other clause stands, §3:8, §3:12–§3:14, §5:4, §5:7, §5:8, §9:2, §9:5 and §9:6 included.
- **Partially supersedes** [ADR-0298](0298-the-gateway-names-a-browser-device-on-each-request-and-the-hub-checks-every-request-by-one-table.md) — **one scope.** **§5:1's table, in the addition alone**: its command-or-query row also names `story_page`, `story_standing`, `add_story_note` and `move_story_members`, the story commands ADR-0300 §8:3 adds to `AssistantEngine` (§9 below). No other row changes, and every other clause stands, §5:3 and §5:4 included.
- **Extends, and replaces no sentence of,** [ADR-0289](0289-a-story-store-holds-which-experiences-belong-to-the-same-matter.md). §2:5's enumeration of what happened gains `decided` under its own *"added to and never renamed"*, and a `decided` line carries two fields beside those §2:4 lists, which says what each line carries without closing the list, unlike §3:14's *"and no others"*. §2:7 stands: the new fields hold identities and an enumeration, never free text.

## Context

**Gap 1: the matters pass has no record of what it decided.** ADR-0300 §9:2 has a
tidy-up raise a flag *"when the page looks like two matters, or like another story, by
naming that story; the flag is recorded by identity in its version"*, and makes
*"Understanding linking one input to two stories"* a flag as well, *"and its record is
the change log's lines"*. §9:3's matters pass *"decides each flag: merge, split, move
members, group stories under a larger one, or leave them"*, and §9:6 puts each story
change in the story's change log, shown on request.

Nothing records that a flag was decided. A merge, a split or a move leaves change-log
lines, but no line says which flag it answered, and a decision to leave the stories as
they are changes nothing and so leaves no line at all. Each run of the pass would
decide the same flags again. And the tidy-up, shown nothing of what was decided, may
raise the same flag on its next version, because the page still looks the same to it.

**The owner's ruling** (2026-10-08, option 2): the matters pass records each decision in
the story's change log, a decision to leave included. The record is durable and shown
on request like every other story change, and a decided flag is revisited only when
something new suggests it, the way a careful human assistant remembers having checked
that two matters are separate.

**Gap 2: a page write is not refused when the story's members changed.** ADR-0300 §3:10
refuses a page write *"where the version it was built on is no longer the current
one"*, and a split or a move writes no version. So a split or a move that lands while a
tidy-up's model call is out does not refuse that run's write (#2761). A probe at
`c41cca1b` against the canonical fake and the SQLite store gives the same answer on
both: a story holding `a-1` and `a-2` is read, `a-2` is split off, and a draft built on
the read, with a safety-net note resting on `a-2` and taking in both episodes, is
written. The safety-net note is written onto the story that no longer holds `a-2`. The
version records taking in `a-1` only: both stores pass over a name that is no longer
pending, as `StoryStore.write_page` states (*"a name that was not is not recorded as
taken in"*), so #2761's further claim that the version records taking in the moved
episode does not hold as built. The page's lines, built on what the run read, are
written all the same.

The tidy-up (#2758) narrows the window from its own side: it re-reads the story's
members just before the write and writes nothing where an episode it took in, or a
safety-net note rests on, has left or been linked again. The read and the write are two
store calls, so the window is one round trip wide, and the guard is the tidy-up's own,
not the store's.

**The code at `c41cca1b`.** `StoryChange` has the six members ADR-0289 §2:5 lists.
`StoryLogLine` carries `sequence`, `story_id`, `change`, `member`, `other_story`,
`actor`, `trigger` and `at`. A tidy-up's flags are `StoryFlag` values (`kind`, and
`story` exactly on `like_another`) in `StoryPageVersion.flags`. The refusals of a page
write are `StoryPageRefusalReason`'s five members, and the CLI's story inspection
renders `StoryChange`, `StoryRefusalReason` and the page refusals by exhaustive
matches whose coverage tests fail on an unrendered member.

## Decision

We will name every flag by identity, record each decision on it as a `decided` line in
the change log of the stories it concerns, written in the same transaction as the change
it decides, and have the matters pass decide only flags no such line answers. The
tidy-up and the pass are shown the decisions already recorded, and a decided flag is
raised again only on something new. And `StoryStore.write_page` refuses, inside its
transaction, a page resting on or taking in what its story does not hold. ADR-0300's
four story commands take ADR-0298's command-or-query row. Every clause below stands
alongside ADR-0300, ADR-0298 and ADR-0289 except where this decision's header names a
scope it replaces.

### 1. Status and scope

> **Normative.** This document remains `Proposed` until the reviews
> `CONTRIBUTING.md` → "Finishing an ADR PR" requires have returned green on one tree
> and the owner's authorization to ratify stands; an assigned number or a green review
> alone does not change its status.

> **Normative.** No implementation, canonical fake included, implements this decision
> until this numbered ADR has merged `Accepted` under ADR-0015 §5.

### 2. What names a flag

> **Normative.** A flag a tidy-up raised is named by the story whose page version
> recorded it, that version's number, and the flag as the version records it: its kind
> and, on `like_another`, the story it names.

> **Normative.** A flag understanding raised is named by its activation. It exists where
> `added` lines naming that activation as their member, with the actor `understanding`
> and that activation as trigger, stand on two or more stories.

> **Normative.** The stories a flag **concerns** are, for a tidy-up's flag, the story
> that raised it and then, on `like_another`, the story it names; for understanding's
> flag, each story holding one of the lines that make it a flag, in the order of those
> lines' sequence numbers. Each is followed through merges to the story it was merged
> into, and each story is counted once, at its first place in that order.

> **Normative.** A flag raised in a later version is a different flag from one raised
> in an earlier version, though its kind and the story it names are the same.

An activation's understanding flag cannot be raised twice: the story-links stage makes
its decision once per activation (ADR-0300 §6:10), and that decision writes every one of
the lines. Its stories need not be part of its name, because a `decided` line is written
on each of them (§3).

### 3. A decision is a line in the change log

> **Normative.** `StoryChange` gains the member `decided`.

> **Normative.** A `decided` line carries, beside the fields ADR-0289 §2:4 lists, the
> flag it answers, named as §2 names it, in a field `answers`, and the outcome, in a
> field `outcome`. It names no member and no other story, and carries no trigger. Its
> actor is the actor that decided.

> **Normative.** The outcome is a closed enumeration, `StoryDecision`, added to and
> never renamed, whose members are `merged`, `split`, `moved`, `grouped` and `left`,
> one for each of ADR-0300 §9:3's answers. `left` means the decider changed no story.

> **Normative.** A decision writes one `decided` line on each story the flag concerns,
> those stories followed through merges as they stand once the change it records is
> applied, so no line is written on a merged story. The lines follow the change's own
> lines, in the same transaction.

> **Normative.** Every decision writes its `decided` lines, a merge, a split, a move and
> a grouping included. A change's own lines say what changed, and its `decided` lines
> say which flag it answered.

**Why one uniform line.** A change line names a member or another story and has no room
for a flag, a decision to leave writes no change line at all, and a reader of the log,
the pass included, then asks one question of one kind of line: is there a `decided`
line answering this flag? Writing the line in the change's own transaction means a
change and the record of what it answered stand or fall together, so a pass that
stopped between the two cannot split a story a second time over a flag it had already
answered.

### 4. The store

> **Normative.** `StoryStore` gains `leave_flag(flag, *, actor)`, which writes a
> decision with the outcome `left` and changes no story's members. An applied one
> answers a `StoryOutcome` naming the first story it wrote a line on, in the order
> §2's stories a flag concerns are given, and counting its lines.

> **Normative.** `create`, `link`, `merge`, `split` and `move` gain a keyword `answers`,
> defaulting to none. Given a flag, the operation writes that decision in its own
> transaction, with the outcome its kind gives: `merge` writes `merged`, `split` writes
> `split`, `move` writes `moved`, and `create` and `link` write `grouped`.

> **Normative.** A `create` or a `link` given a flag to answer names only story members,
> and one naming an activation member is malformed, a `ValueError`.

> **Normative.** `StoryRefusalReason` gains `unknown_flag`, where the flag names no flag
> the store's records hold under §2, and `already_decided`, where a `decided` line
> already answers it. Each refusal names the flag, in a field `flag` of `StoryRefusal`
> set exactly on those two reasons.

> **Normative.** An operation given a flag checks it after every check the operation
> already makes, `unknown_flag` first, and a refused operation writes nothing, its
> change included.

> **Normative.** `AssistantEngine` gains nothing. No write through the engine surface
> answers a flag, and every one still carries `owner` (ADR-0289 §4:4).

The store reads only its own records for these checks: the version log for a tidy-up's
flag, and the change log for understanding's, under ADR-0289 §1:3. Because the check for
`already_decided` is made inside the deciding write's transaction, two passes cannot both
answer one flag, whatever their timing.

### 5. The matters pass decides each flag once

> **Normative.** The matters pass decides only flags that no `decided` line answers,
> and writes each decision through `answers` or `leave_flag` with the actor
> `matters_pass`.

> **Normative.** A flag whose stories have since come together is recorded `left` by
> rule, without a model call: a `like_another` flag whose two stories are one, and an
> understanding flag fewer than two of whose stories still hold its activation.

> **Normative.** For each flag it decides, the pass is shown the `decided` lines on the
> stories the flag concerns, and its instruction states that a flag raised again after
> a decision is decided as before unless what came to those stories since bears on it.

> **Normative.** Where the store refuses the change the pass chose for a reason other
> than `unknown_flag` or `already_decided`, the stories stay as they are and the pass
> records the flag `left`. Where it refuses with either of those two, the pass writes
> nothing more for that flag.

So a merge, a split, a move or a grouping that the store will not make, such as one that
would form a loop, is not proposed again on every run: it is recorded as what happened,
the stories left as they were, and a later flag raised on something new reopens it.

### 6. Something new

> **Normative.** A tidy-up of a story also reads the `decided` lines on that story's
> change log, newest first, up to a number the lane that builds it sets as a
> composition-root constant, and renders each by its outcome, the flag it answers and
> the story that flag names.

> **Normative.** The tidy-up's instruction states that a flag one of those decisions
> answered is raised again only where what this run takes in bears on it.

> **Normative.** No rule drops or refuses a flag because a decision answered an earlier
> one of the same kind naming the same story. A flag raised again is a new flag (§2)
> and the pass decides it, shown the earlier decision (§5).

**Something new**, then, is what a later version takes in: an entry or an episode that
came to the story after the decision. Whether it bears on the flag is the tidy-up's
judgment, and then the pass's, as it would be a human assistant's. What the rule fixes
is the cost of a mistaken re-raise: the pass decides a flag once, so a flag comes back
only with a new version, and a version is written only by a tidy-up, which before the
phases runs only where something is pending (ADR-0300 §5:12) and after them only where
planning chooses it (ADR-0300 §10:4). A re-raise costs one decision, by a pass shown
what it decided before, never one decision per run.

Because a `like_another` decision is written on both stories (§3), each story's tidy-up
is shown it, so neither raises the pair again on nothing new.

### 7. A page write refuses what its story does not hold

> **Normative.** `StoryPageRefusalReason` gains `not_held`.

> **Normative.** `StoryStore.write_page` refuses, inside its transaction, a draft any of
> whose safety-net notes rests on an activation that is not one of the story's members
> when the write runs, or that names as taken in an episode that is not one of the
> story's members, or a note the story does not hold, when the write runs. The refusal
> is `not_held`, and the write writes nothing.

> **Normative.** A `not_held` refusal names the activation or the note it was refused
> over: the activation in a field `activation` of `StoryPageRefusal`, set exactly on a
> `not_held` naming one, and the note in its `note` field, which is then set on
> `unknown_note` and on a `not_held` naming a note, and never both fields at once.

> **Normative.** The check is made after `unknown_note` and after a flag's
> `unknown_story`, and before `over_cap`: the safety-net notes in the draft's order, then
> the episodes taken in, then the notes taken in, and the first that fails is the one
> reported.

> **Normative.** A name the story holds but that was not pending at the draft's `as_of`
> is still passed over and not recorded as taken in, as `write_page` states today.

Grounding. ADR-0300 §3:13 and §3:14 move every entry resting on an activation a split or
a move moves, so after either, a note resting on a moved activation is on the other
story, and §3:8 has a version take in only what is pending on its own story. A page
written over a story that has lost an episode its run read was built on content that is
now another story's; refusing it leaves the page as it was, and the next tidy-up writes
it from what the story holds (§3:13's *"Each part's next tidy-up writes its page"*). A
merge of the story itself is refused already, as `merged_story`, and a merge into it
removes nothing.

This does not make the store hold that every note rests on an activation its story
holds: an unlink leaves the notes resting on the unlinked activation where they are
(ADR-0300, *What stays open*). It holds only that no page write adds such a note, or
records taking in what the story no longer holds.

### 8. The wire and the CLI

> **Normative.** The store lane advances `PROTOCOL_VERSION`, on ADR-0300 §12:2: the
> engine's story log carries `StoryLogLine`, the engine's story writes carry
> `StoryRefusal`, and the story commands carry `StoryPageRefusal`, so a peer at the
> earlier version would refuse a `decided` line or a new refusal.

> **Normative.** The CLI's `story show` renders a `decided` line with its outcome and
> the flag it answers, by identity, and the CLI renders the new refusal reasons wherever
> it renders their enumerations.

### 9. The story commands' row in the route table

ADR-0298 §5:1 classifies *"Every method on the promoted surface"* in exactly one row of
its table, and the table names its methods one by one. ADR-0300 §8:3 adds four story
commands to `AssistantEngine` after that table was written, and the table does not name
them, so by ADR-0298 §5:3 they would be refused to every device but `hub`. The story
commands' lane ([#2760](https://github.com/leonapivato/ai-assistant/pull/2760)) placed
them, under the names below, in the command-or-query row of
`ai_assistant.wire.routes.ROWS`, beside ADR-0289's nine story methods; this section is
the decision that row needs.

> **Normative.** `story_page`, `story_standing`, `add_story_note` and
> `move_story_members` are classified in ADR-0298 §5:1's command-or-query row: the
> requesting device must hold the role of source of commands and queries.

They read and write the assistant's own story records for the owner, as the nine story
methods already in that row do: `story_page` and `story_standing` read a story as
`story` and `story_log` do, and `add_story_note` and `move_story_members` write one as
`link_story` and `split_story` do. None is input to the assistant, a conversation's
traffic or a spoke's, which the other rows hold. Nothing is left to build: the row
already holds them.

### 10. Delivery

This section is guidance for the lanes, except where marked.

1. **The store** (`core` with `memory`): §§2–4 and §7, as a triad with the SQLite store
   under ADR-0300 §3:16 and ADR-0137 §2, with §8. It lands after the story commands
   ([#2760](https://github.com/leonapivato/ai-assistant/pull/2760)), which render the
   page refusals, and before the cutover.
2. **The matters pass** (`orchestration`), ADR-0300 §13's lane 6: the pass itself with
   §5, and the tidy-up's §6 reads and instruction. It lands after the store lane.

> **Normative.** The store lane also changes the CLI's story inspection, in
> `interfaces/`, but only to render the members and fields this decision adds, because
> its coverage tests fail on any member it does not render; that is the whole of its
> reach outside the triad, the SQLite store and `PROTOCOL_VERSION`.

The SQLite store's file gains what a `decided` line carries under a new layout version,
migrated in place as it was for ADR-0300's page; no line written before it changes.

Until the store lane lands, the tidy-up's own re-read (#2758) is what narrows #2761's
window, and nothing of either decision is live before the phases' cutover (ADR-0300
§13).

### 11. Relationship to earlier decisions

| Earlier decision | What changes |
| --- | --- |
| ADR-0300 §3:10, §5:2, §5:6, §9:3 | As this ADR's header states |
| ADR-0300 §3:8, §3:12–§3:14 | Nothing: a version still takes in only what is pending on its own story, and merges, splits and moves still carry entries; §7 refuses the write those clauses already make wrong |
| ADR-0300 §5:4, §5:7, §5:8 | Nothing: the tidy-up still produces flags and nothing else, the hub's checks are unchanged, and a refused write still writes nothing |
| ADR-0300 §9:2, §9:5, §9:6 | Nothing: flags are raised as before, wrong links are fixed by the same hands, and decisions are among the changes the story commands show on request |
| ADR-0300 §12:2 | Nothing: §8 applies it |
| ADR-0289 §2:4, §2:5 | Extended, no sentence replaced, as this ADR's header states |
| ADR-0298 §5:1 | As this ADR's header states |
| ADR-0298 §5:3, §5:4, §5:6 | Nothing: a method in no row is still refused, the closure test still binds, and the command role is still checked before dispatch |
| ADR-0289 §1:3, §2:7, §2:8, §3:11, §4:4 | Nothing: the store reads only its own records, no field holds free text, a decision rides its change's transaction, no line is written on a merged story, and the engine still writes as `owner` |

> **Normative.** This numbered draft records its replacements on the status lines and
> in a dated header note of ADR-0300 and ADR-0298, atomically with this ADR under
> ADR-0070 and ADR-0082, preserving their ratified bodies. The replacements take effect
> on this ADR's ratification.

## Consequences

**What becomes possible.** A flag is decided once and the decision is kept where every
other story change is, so "I checked, they're separate" survives the next run, the next
tidy-up and a look from the user. A decision and the change it made cannot come apart.
A page is never written onto a story that has lost what the page was built on, whoever
moved it and however long the model call took.

**What it costs.** A wider `StoryStore` contract: one operation, a keyword on five, two
membership refusals and one page refusal, a log line with two more fields, and a
`PROTOCOL_VERSION` step. The tidy-up's prompt grows by the decisions it is shown, and
the pass's by the decisions on each flag's stories.

**What stays open.**

- **How the pass finds its flags.** It can read them from the version logs and change
  logs ADR-0289 §3:14 and ADR-0300 §3:10 already provide, which reads every story on
  every run. A read of undecided flags would be another addition to the store's reads,
  for its own decision, if the test hub shows the scan matters.
- **Understanding is not shown the decisions.** A later activation linked to the same
  two stories raises a new flag, which the pass decides shown the earlier decision.
  Showing understanding the decisions would be a change to ADR-0300 §6.
- **A line citing a note its story no longer holds**, as a page does after a split until
  the next tidy-up, is not refused by §7. Whether the store should refuse it depends on
  how the tidy-up treats the lines it keeps, which is the tidy-up's to decide first.
- **The user's own reorganising.** A merge, split or move through the story commands
  answers no flag; a flag it settled is recorded `left` by rule (§5), and any other the
  pass decides on the stories as they then stand.
- **Decisions do not expire.** If the test hub shows an old decision suppressing a flag
  it should not, a bound on which decisions the tidy-up is shown is the place to add
  one.

## Alternatives considered

- **Change lines as the record, and a line only for leaving them.** No change line has
  room for the flag it answered, so every reader would infer it, and two kinds of line
  would mean the same thing.
- **The decision recorded outside the change log**, in the version log or a table of
  its own. The owner ruled for the change log, where every other story change is shown.
- **The decision written in its own transaction, after the change.** A pass that stops
  between the two leaves the flag open over a change already made, and the next run can
  make it again.
- **One operation taking any outcome.** It could record `merged` where nothing was
  merged; tying the outcome to the operation that makes the change cannot.
- **Dropping a re-raised flag where the run took in nothing.** Nearly every tidy-up takes
  something in, so the rule would rarely bind, and taking something in is not the same
  as something bearing on the flag; the pass already decides each flag once.
- **Refusing any page write after a membership change since its read**, extending
  `page_moved_on`. Understanding links an activation into a story on every pass, so most
  page writes would be refused over changes that did not touch them; §7 refuses only what
  the draft rests on or takes in.
- **The tidy-up's re-read alone.** It leaves a round trip's window, and protects no other
  writer of a page.
