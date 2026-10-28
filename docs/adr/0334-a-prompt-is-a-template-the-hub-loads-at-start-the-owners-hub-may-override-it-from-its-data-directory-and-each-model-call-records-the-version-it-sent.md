# 334. A prompt is a template the hub loads at start, the owner's hub may override it from its data directory, and each model call records the version it sent

- Status: Partially superseded by ADR-0335 (§8:2, in the addition alone: the `prompt` key also holds the flags the code computed for the call) and ADR-0337 (§1:3 and §2:1, each in the addition alone: a ninth prompt, `follow_up`, sent as the last user message) and ADR-0346 (§2:1 and §2's table: `observer_commit` leaves the declared set, and `observer_framing` and `observer_placement` join it) and ADR-0353 (§2:1's table, understanding's row, in its flags: none)
- Date: 2026-10-20
- Scope: the instruction, the system message, of each model call the hub makes (§2's table): where its text lives, how the owner changes it without a pull request while the prompts settle, what binds a changed text, how a reply is traced to the text that produced it, and what the tests check meanwhile.
- Dependency: [ADR-0314](0314-a-diagnostic-record-keeps-what-each-phase-was-given-and-returned-and-nothing-reads-it-back.md) and [ADR-0333](0333-the-observer-writes-diagnostic-entries-in-a-file-of-its-own-beside-the-activation-it-learned-from-and-the-viewer-shows-what-was-learned.md), as their status lines leave them.
- Authorization: on 2026-10-20 the owner directed: "changing the prompts are going to [be] common for the beginning, so it would be nice for the infrastructure to be dynamic for a while. It's fine to sacrifice testing and documentation for a little until we settle on prompts." Everything below is the dispatcher's and this lane's recommendation, not an owner ruling. The dispatcher assigned 0334. The owner reads it before it is ratified (§1:1).
- Changes no Protocol and no type in `core/protocols.py` or `core/types.py`, and nothing the wire carries; `PROTOCOL_VERSION` does not move. `Settings` gains one field (§3:3).
- **Partially supersedes**, in the clauses §10's first table names: ADR-0314 and ADR-0333.
- Partially superseded: 2026-10-20 by ADR-0335 — §8:2, in the addition alone: the `prompt` key a given entry carries also holds, for each flag the prompt declares, the value the code computed for that call (ADR-0335 §9:1). Every other clause stands. This replacement takes effect on ratification of ADR-0335. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; the ratified body below is preserved.
- Partially superseded: 2026-10-21 by ADR-0337 — §1:3, in the addition alone: for `follow_up`, the template is the request's last user message, and the system message is the followed call's own (ADR-0337 §6:3). §2:1, in the addition alone: a ninth prompt, `follow_up`, declaring no flag and no value (ADR-0337 §6:1). Every other clause stands. This replacement takes effect on ratification of ADR-0337. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-23 by ADR-0346 — §2:1 and §2's table: `observer_commit` leaves the declared set, and two prompts join it, `observer_framing` and `observer_placement`, in `orchestration/observer/prompts.py`, each declaring no flag and the values its lane declares for the code-owned text it names (ADR-0346 §10:1). Every other clause stands. This replacement takes effect on ratification of ADR-0346. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-27 by ADR-0353 — §2:1's table, understanding's row, in its flags: understanding declares none, and every part of its instruction is sent on every call (ADR-0353 §8:3). Every other clause stands. This replacement takes effect on ratification of ADR-0353. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.

## Context

**The gap.** Every instruction the hub sends a model is a string constant in the module
that sends it, so every change to one is a reviewed pull request, and tests pin parts of
their wording. The owner and the dispatcher are reading the prompts in the activation
viewer (ADR-0316) and expect to change them often before they settle; understanding's
first reading alone produced eight changes, among them regrouping its paragraphs by topic.
At a pull request and a review round per edit, that loop is slow, and each round reviews
wording that the next reading may replace.

**What already binds an instruction.** Many ratified clauses state what an instruction
says: ADR-0329 §6:1–§6:5 and §6:8 for planning's candidates and reliance, ADR-0321 §2:4,
§2:9 and §2:11 for approval, and others across the understanding, story and digest
decisions. They bind content, not words: they say what an instruction conveys and leave its
wording, order and structure open. Separately, the rules the code enforces — label
validation, parsing and the one repair, attribution in the rendered request, the evidence
floor, the admission rules, authorizing's checks — hold whatever a model is told.

**What the record can and cannot carry.** Understanding, planning, digesting and the
observer write a given entry before each model call, holding the messages sent, the
instruction among them (ADR-0314 §4, ADR-0333 §2). The story tidy-up, the matters pass and
the memory reconciler write no entries. ADR-0314 §3:2 keeps every entry's body out of every
prompt, which is why a tool that re-runs recorded inputs through another prompt is not
part of this decision (Alternatives).

**Who may change what a hosted person's assistant is told.** The #879 ruling lets the
owner host hubs for other people, on terms that say the operator performs setup acts only
at the person's request and never an act carrying the person's authority. Each hosted hub's
data directory is its own; its image is built from `main`, so a changed default reaches it
at its next deploy.

## Decision

We will move each instruction's text out of its module into a template file shipped in the
package, let the owner's hub replace any one of them with a file in its data directory, read
at start, and record on every model call's given entry which template, in which version, it
sent. An override is held to the same ratified clauses as the default it replaces, and a
settled override becomes the default through a normal reviewed pull request. Tests stop
pinning wording and keep pinning behaviour.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the owner, having read
> it, has authorized its ratification. An assigned number or a green review alone does not
> change its status.

> **Normative.** No lane implements this decision before it merges `Accepted`. The lane
> that builds §3's mechanism merges before any lane that moves a second prompt.

> **Normative.** This decision governs the system message of each model call §2's table
> names, and a model call added later carries its instruction the same way. The request a
> call renders, the tool declarations it offers and any repair statement it sends stay in
> code, and nothing in this decision lets an override reach them.

### 2. The prompts

| Name | Module | Its text today | Flags | Values |
| --- | --- | --- | --- | --- |
| `understanding` | `orchestration/understanding.py` | `_instruction`: `_READING`, `_RECALLED`, `_STORIES`, `_ANSWERS`, then `_REPLY_SHAPE` or `_STORY_REPLY_SHAPE` | `recalled`, `stories` | none |
| `planning` | `orchestration/planning.py` | `_instruction`: `_ROLE` through `_NOTES_AND_ROUNDS` | `takes_message`, `story_calls`, `story_reads`, `approved`, `candidates`, `reliance` | `APPROVED_ACTION_TOOL`, `NOTE_RELIANCE_CAPABILITY`, `_NEEDS_YOUR_YES` |
| `digesting` | `orchestration/digesting.py` | `_INSTRUCTION` | none | none |
| `story_tidy_up` | `orchestration/story_tidy_up.py` | `_INSTRUCTION` | none | `STORY_SUMMARY_CAP_CHARS` |
| `matters_pass` | `orchestration/matters_pass.py` | `_INSTRUCTION` | none | none |
| `observer_scout` | `orchestration/observer/prompts.py` | `SCOUT_INSTRUCTION` | none | none |
| `observer_commit` | `orchestration/observer/prompts.py` | `COMMIT_INSTRUCTION` | none | none |
| `memory_reconciler` | `memory/_reconciler.py` | `_SYSTEM_PROMPT` and `_ENVELOPE` | none | none |

A flag is a condition the code computes for a call, such as whether `remember` is offered
recording candidates; a value is text the code owns, such as a capability's name, the line
code appends to a message, or a cap the code enforces.

> **Normative.** The prompts are the table's eight, each named by its first column, and
> each declares in its module the closed set of flags and values its template may name:
> those the table lists, under names the implementing lane chooses, which are the
> conditions and code-owned values its instruction uses today.

### 3. Where the text lives, and when an override takes effect

> **Normative.** Each prompt's default is one template file shipped as package data beside
> the module that sends it. The module keeps no copy of the text.

> **Normative.** The lane that moves a prompt into its template changes no character the
> model is sent, under any combination of the prompt's flags.

> **Normative.** `Settings` gains `prompt_overrides`, a boolean whose default is false.
> Where it is true, a file `<name>.txt` in the directory `prompts` of `Settings.data_dir`
> replaces that prompt's default whole. Where it is false, the hub reads no file in that
> directory.

> **Normative.** The hub reads and checks every default and every override once, at start,
> before the API accepts a request, and each call uses what was read until the hub stops.
> Nothing watches the directory; a changed file takes effect at the next start.

> **Normative.** The composition root reads the files and hands each module its template's
> text and version, as it hands it every other dependency. The template form (§4) is
> implemented once, in a `core` module that does no I/O, so that `orchestration` and
> `memory` render templates without importing each other.

### 4. The template form

> **Normative.** A template is UTF-8 text. `$name` or `${name}` is replaced by the value of
> that name, and `$$` by one `$`. A line holding only `$if name`, `$if not name`, `$else` or
> `$end` opens, divides or closes a block, which is included where the flag's value says;
> blocks nest. Nothing else in a template is interpreted.

> **Normative.** The code computes every flag and supplies every value. A template chooses
> what text to show under which flags, and never sets a flag's or a value's value.

> **Normative.** A template may name fewer of its prompt's flags and values than the
> prompt declares, and never one it does not declare.

> **Normative.** Each default renders under every combination of its prompt's flags, and a
> test shows it.

### 5. A malformed override, and the directory's safety

> **Normative.** The hub refuses to start, before the API accepts a request, naming the
> file and its defect and never its content, where: `prompt_overrides` is false and the
> directory holds anything; an entry in it is not a regular file or names no prompt; a file
> is not UTF-8 or holds only whitespace; a template names an undeclared flag or value,
> leaves a block unbalanced, or holds a `$` that is none of §4:1's forms; or the directory
> or a file in it is owned by a user other than the hub's, or is writable by its group or
> by others.

> **Normative.** An override's file is Tier 1 under ADR-0004 §1, and its text never reaches
> a log (ADR-0004 §5).

> **Normative.** The running hub creates, writes and deletes nothing in the directory.
> Deleting the owner's data destroys it with every other entry of the data directory
> (ADR-0126 §1:2), and a backup and its restore carry it as they carry the rest (ADR-0123).

It is not a store under ADR-0326 §2:2, because the hub never writes it.

### 6. Who may override, and on which hub

> **Normative.** Only the owner, or the dispatcher at the owner's direction, places,
> changes or removes an override.

> **Normative.** `prompt_overrides` is true only on the owner's hub, or on a hub the owner
> runs over a copy of that hub's data directory. A hub hosted for another person under the
> #879 ruling runs the shipped defaults, a changed prompt reaches it only by promotion
> (§7:3) and a deploy, and nobody places an override in its data directory.

> **Normative.** An override carries no text taken from a diagnostic entry (ADR-0314 §3:2).

Hosted hubs are excluded because a person was told the operator acts on their hub only at
their request and never with their authority (#879). An unreviewed change to what their
assistant is told is neither; a reviewed default that reaches every hub at its deploy is
the system changing, as any release does.

### 7. What binds an override

> **Normative.** Every ratified clause about what an instruction says binds an override as
> it binds the default it replaces. An override may reword, reorder or regroup the
> instruction, add to it, and cut what no clause requires; its writer checks it against
> those clauses before placing it, and nothing mechanical does.

> **Normative.** No template, override or flag changes what the code accepts, refuses,
> records or runs. Label validation, parsing and the one repair, attribution in the
> rendered request, origins, the evidence floor, the admission rules, the observer's policy
> and authorizing's checks stay in code, with their tests.

> **Normative.** An override is promoted by a reviewed pull request that makes its text the
> prompt's default, and that review reads it against the clauses §7:1 names as it reads any
> change to the package.

> **Normative.** A change to what a ratified clause requires an instruction to say is a
> change to that decision: its ADR merges before an override or a default carries it.

> **Normative.** The deploy that installs a promoted text on the owner's hub removes the
> override whose version equals the new default's, and leaves an override the owner has
> changed since.

### 8. Each call records its prompt's version

> **Normative.** A template's version is the first twelve hexadecimal digits of the
> SHA-256 of its file's bytes, whether the file is a default or an override.

> **Normative.** Where `diagnostic_record` is true, each given entry written for a model
> call whose instruction a template supplied carries `prompt`: the prompt's name, its
> template's version, and `default` or `override`.

> **Normative.** At start the hub logs, for each of §2's prompts, its name, its template's
> version, and `default` or `override`, and nothing of its text.

A version identifies a text and carries none of it, so the start's line logs no Tier 1
data. The story tidy-up, the matters pass and the reconciler write no diagnostic entries; because
a template is read once per start, the start's line names the version each of their calls
sent until the next start. The viewer shows the key as part of the entry, whole (ADR-0316
§3:3); a display or filter by version is left to a later decision.

### 9. Tests while the prompts settle

> **Normative.** No test asserts the wording of a template or of an instruction rendered
> from one, by equality, substring, pattern or length. The lane that moves a prompt retires
> the tests of its wording.

> **Normative.** A test that would fail where a template's text alone changed is a test of
> wording; every other test is a test of behaviour, and stays. A test may render a template
> and assert that it rendered, or which flags and values the code handed it.

> **Normative.** A test a ratified clause itself requires stays as that clause has it.

The behaviour tests cover which flags the code computes for which call, the values it
supplies, the template form, the start's refusals, and every code rule §7:2 names.
ADR-0098 §9's attribution test is over the rendered request, which stays in code (§1:3).

### 10. How long it lasts, and relationship to earlier decisions

> **Normative.** This decision stands until a later ADR ends or changes it. The owner ends
> the experiments on their hub by removing every override from the directory and setting
> `prompt_overrides` to false; the hub then runs the defaults from its next start.

Superseded in part; every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0314 | §4's table, which §4:1 binds, in the addition alone: a model call's given entry also carries its prompt's name, version and origin | §8:2 |
| ADR-0333 | §2's table, which §2:1 binds, in the addition alone: the same, for the observer's given entries | §8:2 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0329 §6:1–§6:5, §6:8; ADR-0321 §2:4, §2:9, §2:11; every other clause about what an instruction says | Nothing: each binds every instruction sent, default or override (§7:1) |
| ADR-0314 §3, ADR-0333 §4 | Nothing: no entry is read back, and none reaches a prompt (§6:3) |
| ADR-0316 | Nothing: the version is shown as part of the entry |
| ADR-0326 §2:2 | Nothing: the override directory is not a store |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0314 and ADR-0333, atomically with this ADR under ADR-0070 and
> ADR-0082, preserving their ratified bodies. The replacements take effect on this ADR's
> ratification.

## Consequences

**What becomes possible.**
- The owner, or the dispatcher at the owner's direction, changes a prompt by writing one
  file on the owner's hub and restarting it, then reads the result in the viewer, where
  each given entry names the version that produced the reply.
- A version that reads well is promoted by one small pull request, and reaches every hub,
  hosted ones included, at its next deploy.

**What it costs.**
- A malformed override stops the owner's hub, and its Telegram line, until the file is
  fixed or removed. A release that drops or renames a flag or value an override names does
  the same at its deploy, so that deploy fixes the override first.
- Each change waits for a restart.
- No test catches a wording regression in a default; the promotion review and the owner's
  reading do.
- Whether an override honours the clauses about what an instruction says rests on its
  writer until promotion.
- An override masks every later change to its default until it is removed.
- Planning's template carries its conditions inline, which makes the default longer to
  read than its separate constants were.

**Lanes it implies**, each after this merges `Accepted` and in the order the dispatcher
sets, the first before the rest (§1:2):
1. The mechanism and `understanding`: `prompt_overrides`, the template form, the reading,
   the start's checks, refusals and line, and `understanding` moved, with its `prompt` key
   and its wording tests retired.
2. `planning` moved, with its key.
3. `digesting`, `story_tidy_up`, `matters_pass` and the observer's two moved, with their
   keys where they write entries.
4. `memory_reconciler` moved.

**What stays open.**
- **Replay, the next decision:** re-running recorded inputs through a candidate template off
  the live path and showing the replies beside the originals. It needs ADR-0314 §3:2
  changed for an owner-run tool, and its own answers on where it runs, which route it pays
  for, and what it reads.
- A display or filter by version in the viewer.
- Overrides for tool descriptions and for the rendered request's fixed phrases.

## Alternatives considered

- **Overrides per section.** Not chosen: a regrouping moves text across the conditions'
  boundaries (understanding's reading would put the recalled-memory rules in a label table),
  which per-section files cannot express without a code change re-cutting the sections.
  Conditions inside one template express it, and the code still computes every condition.
- **An override binds nothing until promoted.** Not chosen. It narrows every clause about
  what an instruction says, in some two dozen live ADRs, each owed a record under ADR-0082
  §1, and what it adds — trying a text that drops what a clause requires — is the one change
  whose promotion needs an ADR anyway (§7:4). The owner's reading so far keeps every rule's
  content while changing its words.
- **Reading overrides on every call.** Not chosen: one activation could mix versions across
  its rounds, a defect would surface mid-call rather than at start, and a restart is cheap
  on the owner's hub.
- **Falling back to the default on a malformed override.** Not chosen: the owner would read
  replies believing an experiment ran that did not. The refusal names the file at once, and
  the version key would otherwise be the only sign.
- **Overrides on hosted hubs.** Rejected: an operator steering another person's assistant
  outside a reviewed release is an act the #879 terms do not cover.
- **A general template engine.** Not chosen: a new dependency whose expressions, loops and
  attribute access let a template compute, where flags and values suffice.
- **Prompts in a store edited through a surface of the assistant.** Not chosen: a write
  surface needs its own authority design, and a file on the server is already owner-only.
- **New diagnostic sources for the tidy-up, the matters pass and the reconciler.** Not
  chosen: it changes `DiagnosticSource` and adds entries to trace a version the start's line
  already fixes for the run.
- **A replay tool in this decision.** Deferred to the next decision (Consequences).
