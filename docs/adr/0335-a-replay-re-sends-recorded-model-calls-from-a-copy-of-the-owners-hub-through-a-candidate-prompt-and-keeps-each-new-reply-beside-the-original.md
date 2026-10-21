# 335. A replay re-sends recorded model calls from a copy of the owner's hub through a candidate prompt, and keeps each new reply beside the original

- Status: Partially superseded by ADR-0337 (§2:4, §2:5, §3:1, §4:10, §6:1 and §6:2, each in the addition alone: a synthetic suite run anywhere, a case store in the live data directory, repeated samples, and the follow-up after a replayed call)
- Date: 2026-10-20
- Scope: an owner-run tool for judging a prompt change on inputs the hub has already seen: it re-sends the model calls the diagnostic record kept through a candidate template, and reruns the observer, over a copy of the owner's hub's data directory, and the activation viewer shows each new reply beside the one the hub got.
- Dependency: [ADR-0314](0314-a-diagnostic-record-keeps-what-each-phase-was-given-and-returned-and-nothing-reads-it-back.md), [ADR-0316](0316-an-activation-viewer-outside-the-package-shows-the-diagnostic-record-to-the-owner-on-the-server.md), [ADR-0333](0333-the-observer-writes-diagnostic-entries-in-a-file-of-its-own-beside-the-activation-it-learned-from-and-the-viewer-shows-what-was-learned.md) and [ADR-0334](0334-a-prompt-is-a-template-the-hub-loads-at-start-the-owners-hub-may-override-it-from-its-data-directory-and-each-model-call-records-the-version-it-sent.md), as their status lines leave them.
- Authorization: on 2026-10-20 the owner and the dispatcher began reviewing the hub's prompts in the activation viewer, and ADR-0334 left replay as "the next decision" (Consequences). Everything below is the dispatcher's and this lane's recommendation, not an owner ruling. The dispatcher assigned 0335. The owner reads it before it is ratified (§1:1).
- Changes no Protocol and no type in `core/protocols.py` or `core/types.py`, no `Settings` field, and nothing the wire carries; `PROTOCOL_VERSION` does not move.
- **Partially supersedes**, in the clauses §10's first table names: ADR-0314, ADR-0316, ADR-0333 and ADR-0334.
- Partially superseded: 2026-10-21 by ADR-0337 — §2:4 and §2:5, in the addition alone: a suite run of synthetic cases alone, which reads no data directory, copy, record or case store, runs on any machine, by the owner, the dispatcher or a lane the dispatcher briefs (ADR-0337 §4:7). §3:1, in the addition alone: the `keep` and `suite` commands, and the owner's deleting a case, read and write the live data directory's `prompt_cases` directory and nothing else in it (ADR-0337 §4:8, §4:10). §4:10, in the addition alone: a run sends each call as many times as it names, and may send the follow-up question after each response (ADR-0337 §5:4, §7:1, §7:2). §6:1 and §6:2, in the addition alone: a result line for each sample, naming its sample, and carrying the follow-up's answer or failure where one was sent (ADR-0337 §5:4, §7:3). Every other clause stands. This replacement takes effect on ratification of ADR-0337. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; the ratified body below is preserved.

## Context

**The gap.** ADR-0334 lets the owner change a prompt by placing a file and restarting the
hub, and records which version produced each reply. It does not show what a candidate would
have said to an input already seen: an override acts only on activations after the restart,
on whatever arrives, so two versions are never judged on the same input. Nothing may re-send
a recorded input either. ADR-0314 §3:1 keeps every model call from reading an entry, §3:2
keeps every entry's body out of every prompt, and §3:4 has the owner read the record on the
server. The owner's notes of the review so far say, of nearly every proposed rewrite, that
judging old against new on real exchanges needs a replay tool.

**The evidence.** On 2026-10-20 the dispatcher worked the need by hand, outside the package,
on its own computer, over a copy of the owner's hub's data directory made with SQLite's
online backup:

- A script re-sent recorded understanding and planning calls to the hub's model, with the
  recorded system message, data and tools, then asked the model what had been unclear. Its
  answers feed the prompt review. It re-sent entry bodies, which ADR-0314 §3:2 does not
  allow, and it read the record off the server.
- A dry run composed the package over the copy with the episode window narrowed to one,
  ran the observer over every episode with the record on, and read what it learned in the
  viewer, started over the copy on the same computer. It found a reply refused whole for one
  stray key, and a scout habit worth a prompt change.

**What a recorded call holds.** Understanding, planning, digesting and the observer write a
given entry before each model call. It holds the messages sent, the instruction being the one
system message among them, and, for planning, the tools offered (ADR-0314 §4, ADR-0333 §2).
ADR-0334 §8:2 adds the prompt's name, its version and its origin. No entry holds the flags the
code computed for the call, so a candidate template with conditional blocks cannot be
rendered for a recorded call with certainty. No given entry names the model; only planning's
returned entry does, inside the provider's whole response. The story tidy-up,
the matters pass and the memory reconciler write no entries, so nothing of theirs can be
replayed.

## Decision

We will add one owner-run program outside the package, `scripts/prompt_replay.py`. On the
owner's hub's server, it copies that hub's data directory, re-sends the model calls the
copy's record kept, each with a candidate instruction in place of the recorded one, through
the package's own model layer, and writes each new reply into the copy's record beside the
call it replays. It can also rerun the observer over the copy. It never acts, never touches
a live data directory past copying it, and stops at a bound on calls. The activation viewer
shows each replayed reply beside the original. ADR-0314 §3 gives way for this one tool and
for nothing in the hub.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the owner, having read
> it, has authorized its ratification. An assigned number or a green review alone does not
> change its status.

> **Normative.** No lane implements this decision before it merges `Accepted`.

### 2. What the tool is, who runs it, and where

> **Normative.** The tool is one program, `scripts/prompt_replay.py`, outside the
> `ai_assistant` package, so the wheel does not carry it and the hub's deploy neither
> installs nor starts it.

> **Normative.** Nothing in `ai_assistant` imports the tool, names its file or starts it,
> and no service unit, deploy or hub surface starts it.

> **Normative.** The tool adds no dependency: neither `pyproject.toml` nor `uv.lock`
> changes for it.

> **Normative.** Only the owner, or the dispatcher at the owner's direction, runs the tool.

> **Normative.** The tool runs on the server of the owner's hub, as that hub's user.

> **Normative.** The tool reads no data directory, record or copy of either that belongs to
> a hub hosted for another person under the #879 ruling.

Unlike the viewer (ADR-0316 §2:2), the tool imports `ai_assistant`: to send a call through
the package's own model layer (§4:6), to check and render a template by ADR-0334's form
(§4:3), and to compose the observer for a rerun (§7). `scripts/` is in the gate already, as
ADR-0316 §2 found.

### 3. The copy

> **Normative.** The tool reads and writes a copy of the owner's hub's data directory and no
> live data directory, except that its copy step reads the live one.

> **Normative.** The copy step writes the copy into a new directory readable by the hub's
> user alone. It copies each database consistently while the hub runs, and each file of the
> record whole up to its last complete line. It writes nothing in the live directory and
> takes no lock there.

> **Normative.** The copy step writes a marker file into each copy, and the tool's replay
> and rerun refuse a directory that does not carry one, naming the directory.

> **Normative.** A replay and a rerun each hold the copy's instance lock (ADR-0083 §1) for
> the whole run, and refuse where another holds it.

> **Normative.** A copy is Tier 1 under ADR-0004 §1, and stays on the owner's hub's
> server: nothing copies it, or anything in it, to another machine.

> **Normative.** A copy is deleted when the review it was made for ends, and no later than
> `diagnostic_retention` after it was made.

A copy holds raw outside text that the live record's window would have deleted. The second
deadline bounds how long it survives: at most twice the window after the hub wrote it. The
viewer's page reaching the owner's browser through the tunnel is reading, as ADR-0316 §8 has
it, and a replayed request reaching the provider is the egress the hub's own call made; neither
is a copy.

### 4. Replaying a recorded call

> **Normative.** A replay takes given entries from a copy's record, of understanding, of
> each planning round, of each digest part and of the observer's scout and commit calls, and
> sends each one's recorded messages and offered tools unchanged except for its system
> message, which is the candidate's.

> **Normative.** A candidate is a template file, either an override as ADR-0334 §3:3 places
> one or a default from a checkout of the repository, or else the call's recorded
> instruction itself.

> **Normative.** The tool checks a template file as ADR-0334 §5:1 has the hub check an
> override's content, against the flags and values the package it runs from declares, and
> refuses one that fails, naming the file and its defect and never its content.

> **Normative.** The tool renders a template under the flags §9 records for the call, with
> the values the package it runs from supplies.

> **Normative.** Where a given entry records no flags, the tool renders a template for it
> only under flags the run states, and marks each such result as rendered under stated
> flags.

> **Normative.** The tool sends each call through `ai_assistant`'s own model layer, with its
> recorded messages and tools, apart from the system message, and the settings the stage that
> made it sends it with where the record is on.

> **Normative.** A run sends every call to one model, which it names, and falls back to no
> other: a call that model fails is recorded as failed.

> **Normative.** For a planning call, the tool uses a seam of the concrete completer in
> `models/` that sends a round as `PydanticAIToolCallingCompleter` sends it where the record
> is on, summarised thinking included, and returns the provider's whole response.

> **Normative.** That seam writes no entry, binds no activation and is on no Protocol, and no
> stage calls it.

> **Normative.** Each call is sent once for each candidate, and its one response recorded.
> The tool continues nothing: it sends no further round, no repair and no tool's result.

> **Normative.** A call whose given entry the observer wrote under several activations
> (ADR-0333 §2:9) is sent once for each candidate, and its result is written under each of
> them.

> **Normative.** A replay writes no diagnostic entry: the package code it calls is handed no
> `DiagnosticSink`, and no activation is bound while it runs (ADR-0314 §5:4).

The recorded instruction as a candidate is the control: it shows how far the reply moves
with the prompt unchanged, which is the noise any other candidate is read against. Each
call is replayed on its own recorded request. A later planning round and a repair call
therefore carry what the original run produced, not what the candidate would have.
Without the seam, the completer asks for summarised thinking and keeps the whole response
only where it holds a sink (ADR-0314 §5:1–§5:2), so a sinkless replay of a planning call
would change the request and lose the thinking. One model for a run means the candidates
and the control are compared on the same model. A comparison with the hub's own reply may
cross models, where a fallback answered the original or the configuration has changed since,
and each result says which model the original used where the record knows it.

### 5. What it never does

> **Normative.** The tool runs no tool, authorizes nothing and sends no message. A planning
> response's calls and message are recorded as proposed, and nothing else is done with
> them.

> **Normative.** A replay writes nothing but §6's results file, and nothing to a copy's
> stores.

> **Normative.** Nothing the tool prints is taken from an entry or a reply. It prints
> counts, file names, prompt names, versions and failures by class.

> **Normative.** No template file a replay sends carries text taken from a diagnostic entry,
> as ADR-0334 §6:3 has no override carry any.

> **Normative.** The recorded instruction is a candidate only unchanged and only for its own
> call: the tool sends no instruction assembled from an entry's text.

Acting and the message writes write no entry (ADR-0314 §4:3), so no effect and no message
is ever a call the tool could replay. Outside content in a replayed request can steer a
reply, as it can steer the hub's, and the reply is only recorded and shown as text.

### 6. The results, and where they are shown

> **Normative.** A replay writes its results to the file `<activation_id>.replay.jsonl` in
> the copy's record directory, one line for each call and candidate, in ADR-0314 §6:2's line
> form with the source `replay` and the kind `returned`, each line appended whole.

> **Normative.** Each result names the entry it replays, by its file, its line and its
> instant; the run; the prompt's name; the recorded version and origin where the entry has
> them; the candidate's version, its origin as `override`, `default` or `recorded`, and its
> rendered instruction; the flags and whether they were recorded or stated; the run's model,
> and the original call's model where its returned entry names one, or else that it is
> unknown; and the reply as text or the failure, with every part of a planning response,
> thinking included.

> **Normative.** A results file is a file of the copy's record: readable by the hub's user
> alone, Tier 1, and deleted with the copy.

> **Normative.** The viewer shows, for a model call's given entry, each result that replays
> it beside the original reply, each headed by its prompt's name, version and origin, with
> the candidate's instruction one click away.

> **Normative.** The viewer marks, in its list, an activation that has results, and never
> lists a results file as an activation of its own name.

`replay` is no member of `DiagnosticSource`. The package neither writes nor reads it: the
tool writes the line, and the viewer reads it, shows an unknown source as ADR-0316 §5:3
already requires, and stays read-only (ADR-0316 §6:4), so it starts no replay. The viewer is
started over the copy's record on the server, as over any record (ADR-0316 §2:5).

### 7. Rerunning the observer over a copy

> **Normative.** The tool may rerun the observer over a copy: it composes the package over
> the copy's data directory with the diagnostic record on, and with overrides from the
> copy's `prompts` directory where the owner places them (ADR-0334 §6:2), and runs the
> observer until no episode is due or §8's bound stops it.

> **Normative.** A rerun writes only to the copy: its memory store, its plan store and its
> record.

> **Normative.** A rerun runs the observer alone. It starts no hub, listener, line, reader
> or scheduled job, and calls no tool.

> **Normative.** Where a rerun narrows the episode selector's bound or processes an episode
> again, it says so in what it prints.

Over a copy, the rerun may wire the episode selector with a smaller bound than the hub's,
which ADR-0276 §4:4 leaves to the composition, so that episodes still in the hub's window
are due (ADR-0329 §7:1). It may process again an episode the copy records as processed, as
an explicit re-run does (ADR-0329 §12:7). Neither decides a re-run surface for a hub. Its
observer reads no diagnostic entry (ADR-0333 §4:1), and what it learns is shown by the
viewer's learning lane (ADR-0333 §5).

### 8. Cost

> **Normative.** Every call the tool makes is paid through the owner's own provider account,
> with the key configured where it runs, and never a key belonging to another person.

> **Normative.** A run makes at most its bound of model calls: 100, unless the run names
> another.

> **Normative.** Before it sends anything, a replay counts the calls it would make and
> prints the count, and where the count exceeds its bound it sends none.

> **Normative.** A rerun sets the observer's 24-hour budget (ADR-0329 §16:9) to no more than
> its bound.

### 9. What a given entry records for a replay

> **Normative.** The `prompt` key a given entry carries (ADR-0334 §8:2) also holds, for each
> flag the prompt declares, the value the code computed for that call.

A flag is a condition the code computes, such as whether the place takes a message, so the
key carries no Tier 1 data. Values are not recorded: they are code-owned text that the
package the tool runs from supplies.

### 10. Relationship to earlier decisions

Superseded in part; every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0314 | §3:1, in the addition alone: the model calls the replay tool makes through `ai_assistant`'s model layer with a recorded request the tool hands it; §3:2, in the addition alone: a recorded call's request, read from a copy of the owner's hub's record, reaches a model in a replay the owner runs with the tool, and the reply is kept in the copy's record; §3:4, in the addition alone: the server's own tools include the replay tool, which reads a copy of the record on the owner's hub's server; §5:3, in the addition alone: the thinking a replayed planning call returns reaches that replay's results in the copy's record | §3:1, §4:1, §4:6, §4:8, §6:1, §6:2 |
| ADR-0333 | §4:1, in the addition alone: a recorded observer call's request reaches a model in a replay the owner runs with the tool, as for ADR-0314 §3:2; the observer itself still reads no entry | §4:1 |
| ADR-0316 | §3:1 and §3:3, in the addition alone: an activation's replay results marked in the list and shown beside the reply they replay; §5:1, in the addition alone: the results file's name | §6:4, §6:5 |
| ADR-0334 | §8:2, in the addition alone: the `prompt` key also holds the flags the code computed for the call | §9:1 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0314 §2:3, §6, §7 | Nothing: a copy's files are owner-only, the hub's store and sweep are as they were, and a copy is deleted on §3:6's deadline rather than kept like a backup |
| ADR-0314 §3:3 | Nothing: the store is handed to nothing, and the tool reads the copy's files |
| ADR-0316 §2, §4, §6 | Nothing: the viewer imports the standard library alone, follows the directory, binds loopback and writes nothing |
| ADR-0333 §2, §3 | Nothing: a rerun's observer writes its entries as these sections have it, into the copy's record |
| ADR-0334 §1:3, §6:2, §6:3 | Nothing: the request and the tools stay in code and are re-sent as recorded; overrides apply over a copy as §6:2 allows; no template file carries an entry's text (§5:4) |
| ADR-0329 §7:1, §12:7, §16:9 | Nothing: a rerun processes episodes as these clauses have the observer do |
| ADR-0276 §4:4 | Nothing: a narrower bound in a rerun's composition is the composition's choice |
| ADR-0004 §2 | Nothing: a replay's calls go to the provider the hub's calls go to |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0314, ADR-0316, ADR-0333 and ADR-0334, atomically with this ADR under
> ADR-0070 and ADR-0082, preserving their ratified bodies. The replacements take effect on
> this ADR's ratification.

## Consequences

**What becomes possible.**
- The owner reads a candidate's replies to the same inputs beside the hub's, with the
  recorded instruction re-sent as a control, before placing an override or promoting one.
- The observer's prompts are judged over a copy of real data, as the dry run judged them,
  without touching the owner's memory.
- A prompt revision lane can say which replays it ran and what they showed.

**What it costs.**
- The owner pays for every call, on the account the hub uses; the bound caps a run, not a
  day.
- A copy on the server holds raw outside text and other people's words past the live window,
  for up to one more window.
- A rerun loads the package beside the live hub on the same server.
- A replay re-sends one call on its recorded request, so it shows how a candidate reads an
  input, not how a whole activation would have gone under it.
- A candidate naming a flag or value the installed package does not declare is refused until
  a package declaring it is deployed.
- Entries written before §9's key carry no flags, so a candidate with conditional blocks is
  rendered over them only under flags the owner states.
- Work done on another computer, as on 2026-10-20, stays outside what this decision
  allows.

**Lanes it implies**, each after this merges `Accepted`:
1. §9's flags: carried by each ADR-0334 lane, not yet merged, that moves a prompt writing
   entries, and added in a follow-on for any already merged.
2. The completer's seam (§4:8–§4:9), in `models/`, with its tests.
3. After the second, the tool's copy and replay, and the viewer's display, with tests under
   `tests/scripts/`, touching nothing under `src/`.
4. The rerun, in the same program. Where composing the observer alone needs a seam in `app/`,
   that seam is a change of its own under `src/`. The dispatcher may fold this lane into the
   third.

**What stays open.**
- Replays on the owner's computer.
- A view comparing many replays at once, or filtering by version.
- Replaying the story tidy-up, the matters pass and the reconciler, which write no entries.
- Grading replies automatically.

## Alternatives considered

- **A package command not wired into the hub.** Not chosen: ADR-0314 §3:1's "Nothing in
  `ai_assistant` reads an entry back" would have to give way, and so would the record's
  write-only test. Every hub's image, hosted ones included, would also carry a tool for
  reading a person's record.
- **A standard-library program, like the viewer, calling the provider's API itself.** Not
  chosen: it would rebuild the model layer's request by hand, so a reply could differ
  because of how it was sent rather than what it was told.
- **Replaying over the live record.** Not chosen: results would land in a live data
  directory, written by a process other than the hub, and a rerun cannot run there at all.
  A copy is frozen and small.
- **On the owner's computer, over a copy, as on 2026-10-20.** Not chosen: it takes Tier 1
  data, raw outside text and other people's words included, off the server and beyond the
  window's and the sweep's reach, which ADR-0314 §3:4 and ADR-0316 §2:5 keep on the server.
  Choosing it would supersede both in part and needs a rule for where a copy may lie there
  and for how long. In exchange, it is the more convenient route: replays run from the
  dispatcher's clone, and nothing extra loads the hub's server.
- **A separate report.** Not chosen: it is a second place to read, where the viewer already
  shows each call's request and reply.
- **Amending ADR-0334 §6:3 for a replay.** Not chosen: a candidate is a template that may be
  promoted to the package's default and reach every hub, hosted ones included, so a sentence
  lifted from the owner's record would ship in it. A replay needs the record's text only as
  the data it re-sends.
- **Inferring a call's flags from its recorded instruction.** Not chosen: it needs the
  recorded version's text, and two combinations of flags may render alike.
- **Replaying a planning run through all its rounds.** Not chosen: a later round needs its
  calls' results, which only acting produces. The rerun covers the observer's chain, whose
  writes land in the copy's stores.
- **No bound.** Not chosen: a run over a large copy could spend without asking.
