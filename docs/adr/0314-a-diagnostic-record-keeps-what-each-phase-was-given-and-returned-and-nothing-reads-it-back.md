# 314. A diagnostic record keeps what each phase was given and returned, and nothing reads it back

- Status: Partially superseded by ADR-0316 (§3:4, in the addition alone: the server's own tools include ADR-0316's activation viewer) and ADR-0333 (§4's table, §6:1 and §8:1's `DiagnosticSource` row, each in the addition alone: the observer as a source, writing to a file of its own) and ADR-0334 (§4's table, in the addition alone: a model call's given entry also carries its prompt's name, version and origin) and ADR-0335 (§3:1, §3:2, §3:4 and §5:3, each in the addition alone: the owner's replay tool, over a copy of the owner's hub's record) and ADR-0337 (§3:1, §3:2, §4's table, §5:3, §6:1 and §8:1's `DiagnosticSource` row, each in the addition alone: the follow-up question on the owner's hub, and real prompt cases kept from a copy) and ADR-0354 (§4's table, in the additions alone: a structured call's reply shape, usage, model, mode, refusal and failure) and ADR-0355 (§4's table, in the addition alone: a structured call's thinking summary) and ADR-0356 (§5:3's *the next round never carries it*, for planning's own exchange alone)
- Date: 2026-10-13
- Scope: the phases, milestone M43 ([#2815](https://github.com/leonapivato/ai-assistant/issues/2815)): a per-activation record of what each phase was given and what it returned, for the owner to read on the server when a decision cannot otherwise be explained ([#2863](https://github.com/leonapivato/ai-assistant/issues/2863)).
- Authorization: the owner agreed the design on 2026-10-12 in #2863: on all hubs as an opt-in, with a retention window, strictly write-only, raw outside text kept within the window, and forgetting covering it later or the window doing the forgetting. The dispatcher assigned 0314 and authorized ratifying it once its reviews are green. The clauses that settle what that agreement leaves open are listed as such in the pull request.
- **Changes `core`, so it is a contract-surface decision.** Two Protocols, `DiagnosticSink` and `DiagnosticRetention`, three types, one module carrying the activation outside every signature, and two `Settings` fields (§8). No existing Protocol or type changes, nothing the wire carries changes, and `PROTOCOL_VERSION` does not move.
- **Partially supersedes**:
  [ADR-0004](0004-privacy-and-data-handling.md) (§6's view and export limbs, each only as they reach the diagnostic record, which no surface shows and no export carries, and which the owner reads and copies as files on the server);
  [ADR-0308](0308-recall-runs-again-on-what-understanding-found-and-outside-content-reaches-planning-only-as-a-digests-evidence.md) (§6:4's *and go when the activation ends*, for the copy of a held result's text a digest's prompt carries into the diagnostic record, until the record's window deletes it);
  [ADR-0123](0123-a-backup-is-the-cold-data-directory-encrypted-to-a-passphrase-the-operator-holds.md) (§3:1's exclusions, in the addition alone: the diagnostic record's directory; §3:4's exact match, for that directory alone, every file beneath which is excluded).
- Partially superseded: 2026-10-13 by ADR-0316 — one scope. §3:4, in the addition alone:
  the owner reads the record on the server with the server's own tools, ADR-0316's
  activation viewer among them, which stands outside `ai_assistant` and imports nothing
  from it. §3:1–§3:3 and every other clause stand. This replacement takes effect on
  ratification of ADR-0316. This reciprocal header record accompanies the numbered draft
  under ADR-0070 and ADR-0082; the ratified body below is preserved.
- Partially superseded: 2026-10-20 by ADR-0333 — §4's table, which §4:1 binds, in the addition alone: the observer is a source, writing each model call's rendered request and reply, its scout's findings, each finding's outcome and how each attempt ended (ADR-0333 §2). §6:1, in the addition alone: an activation's observer entries are a second file, `<activation_id>.observer.jsonl` (ADR-0333 §3:1). §8:1's `DiagnosticSource` row, in the addition alone: the member `observer` (ADR-0333 §2:1). Every other clause stands. This replacement takes effect on ratification of ADR-0333. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-20 by ADR-0334 — §4's table, which §4:1 binds, in the addition alone: each given entry written for a model call whose instruction a template supplied also carries `prompt`, the prompt's name, its template's version, and `default` or `override` (ADR-0334 §8:2). Every other clause stands. This replacement takes effect on ratification of ADR-0334. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-20 by ADR-0335 — §3:1, in the addition alone: the model calls the replay tool makes through `ai_assistant`'s model layer with a recorded request the tool hands it (ADR-0335 §4:6). §3:2, in the addition alone: a recorded call's request, read from a copy of the owner's hub's record, reaches a model in a replay the owner runs with that tool, and the reply is kept in the copy's record (ADR-0335 §4:1, §6:1). §3:4, in the addition alone: the server's own tools include the replay tool, which reads a copy of the record on the owner's hub's server (ADR-0335 §2:5, §3:1). §5:3, in the addition alone: the thinking a replayed planning call returns reaches that replay's results in the copy's record (ADR-0335 §4:8, §6:2). Every other clause stands. This replacement takes effect on ratification of ADR-0335. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-21 by ADR-0337 — §3:1, in the addition alone: the follow-up asker reads the entries a sink is handed, decides from them which calls to ask about, and its model calls carry them (ADR-0337 §8:4–§8:6). §3:2, in the addition alone: a recorded call's request and response reach the follow-up call's prompt and its answer is kept in the record (ADR-0337 §6:3, §8:9), and a recorded call's request, kept from a copy as a real case, reaches a model in a suite run and its replies are kept in the case store (ADR-0337 §4:2, §4:10). §4's table, which §4:1 binds, in the addition alone: a row for `follow_up`, which writes a returned entry alone (ADR-0337 §8:9). §5:3, in the addition alone: a planning response's thinking reaches the follow-up request about that response, and a real `follow_up` case that keeps it (ADR-0337 §6:6). §6:1, in the addition alone: an activation's follow-up entries are a further file, `<activation_id>.followup.jsonl` (ADR-0337 §8:12). §8:1's `DiagnosticSource` row, in the addition alone: the member `follow_up` (ADR-0337 §8:9). Every other clause stands. This replacement takes effect on ratification of ADR-0337. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-27 by ADR-0354 — §4's table, which §4:1 binds, in the additions alone: a structured call's given entry also carries `reply_shape`, the shape's name and version, and its returned entry, beside the reply as the model wrote it, also carries the model that answered, the mode, the finish reason, a refusal's statement and category, the usage and the returned failure's kind (ADR-0354 §7:1–§7:2). Every other clause stands, §3 included. This replacement takes effect on ratification of ADR-0354. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-28 by ADR-0355 — §4's table, which §4:1 binds, in the addition alone: a structured call's returned entry, understanding's and a digest part's, also carries `thinking`, the provider's summary of its thinking, where the provider gave one (ADR-0355 §5:1, §6:1). Every other clause stands, §3 and §5 included. This replacement takes effect on ratification of ADR-0355. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-30 by ADR-0356 — §5:3's *the next round never carries it*, for planning's own exchange alone: a response's continuation, its thinking included, is handed back to the provider with the work's later rounds, and is held only in memory and in the record, never in the episode or any text anyone reads (ADR-0356 §6:4). Every other clause stands. This replacement takes effect on ratification of ADR-0356. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.

## Context

**The gap.** The two thin-path QA runs (#2849) could not see what the phases were shown or
why they decided what they did. The hub records neither planning's rendered request nor the
place window; the causes of #2856 and #2862 were read from the code; and planning's
thinking, which #2865 turned on, is dropped by `PydanticAIToolCallingCompleter` because it
is none of a round's four parts (ADR-0307 §2:1). On `claude-opus-4-8` the thinking parts
come back with empty text unless the request asks the provider to summarise them (#2865).

**Why not the trace store.** An `EvaluationTrace` references what it is about and never
contains it: no string in it is derived from data (ADR-0119 §2), and that is its point.
This record exists to contain exactly what a trace may not, so it cannot be a trace kind,
and it cannot share the trace database, which is Tier 2 with a year's horizon (ADR-0119
§10), while this record is Tier 1 under ADR-0004 §1 with a window of weeks.

**Why not the episode.** Episodes are what the assistant reads back. A record that holds
raw outside text, thinking and other people's words in a shared place is safe only because
nothing reads it back (#2863).

## Decision

We will keep, where the owner opts in, one file per activation in the data directory that
holds what each phase was given and what it returned, planning's thinking included; give
the pipeline a seam that can only write it; sweep it after a window of thirty days by
default; and leave it out of backups, so that the window is its forgetting.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews
> `CONTRIBUTING.md` → "Finishing an ADR PR" requires have returned green on one tree
> and the authorization to ratify stands; an assigned number or a green review alone
> does not change its status.

> **Normative.** One lane implements this decision, after it merges `Accepted` and before
> M43's acceptance run: the triad of §8's two Protocols, their store, the emitters, the
> thinking, the sweep, the backup exclusion and the wiring, in one change.

### 2. The record and its opt-in

> **Normative.** `Settings` gains `diagnostic_record`, a boolean whose default is false.
> Where it is false, no entry is built and nothing is written.

> **Normative.** Where it is true, the record holds an entry for each thing §4 names, for
> every activation the controller runs, on any hub.

> **Normative.** The record is Tier 1 under ADR-0004 §1. Its directory is created
> readable by the hub's user alone, and each of its files likewise.

> **Normative.** A failure to write an entry never propagates into the work it describes:
> no stage fails, retries or changes its result because an entry could not be written. It
> is logged naming the activation, the source and the failure's class, and never any of
> the entry's content (ADR-0004 §5).

> **Normative.** An externally delivered cancellation is not a failure to write: a write
> it reaches makes its file safe and re-raises it (ADR-0060), as ADR-0119 §3 has a trace
> emitter re-raise one.

### 3. Write-only

> **Normative.** Nothing in `ai_assistant` reads an entry back. No Protocol carries a read
> of the record; no stage, capability, tool, model call, wire operation, gateway route,
> command or export serves or reads it; and no decision the system makes is conditioned on
> it.

> **Normative.** No entry's body, and nothing taken from one, reaches a prompt, a message,
> a memory, an episode, a story, a trace or a log.

> **Normative.** The store lives in `evaluation/`, which no subsystem imports. Each
> emitter is handed a `DiagnosticSink`, which writes; the engine's sweep is handed a
> `DiagnosticRetention`, which deletes files by age and reads no entry; and the store
> itself is handed to nothing.

> **Normative.** The owner reads the record on the server, with the server's own tools.

ADR-0119 §7:3's rule that nothing in the pipeline reads a trace back carries over here and
goes further: a trace has a walk a measure may read, and this record has no read at all.
Because nothing reads it, nothing in it can be repeated to anyone, including what other
people wrote in a shared place.

### 4. What each source writes

| Source | Writes | Given | Returned |
| --- | --- | --- | --- |
| Controller | `controller.py` | | At each step, the rule that answered, the stage it ran, when the step started and ended, and how it ended |
| Understanding | Its module | Its rendered request | The model's reply as text, or the failure |
| Recall | `RecallStage` | Which run, and its cues | Each find, with its id, its score, its band and the cue that found it, and which were kept |
| Planning | Its module; `models/` | The rendered request and the offered tools | The provider's whole response, every part in order, thinking included (§5) |
| Authorizing | Its module | | For each call, the verdict of each check it reached and that check's reason; the message's verdict; and whether the activation had read outside content, with each ground of ADR-0306 §4:5 that held and the record it rests on |
| Digesting | Its module | Each part's rendered prompt | Each part's reply, the items dropped because their source is not one of the call's labels, and the failure's reason where it failed |

> **Normative.** Each source writes what the table gives it, from its own module, through
> the `DiagnosticSink` it is handed. A source's given entry is written before its model
> call or its search, and its returned entry once that returns or fails.

> **Normative.** No phase reads another's entries, and no phase module imports another to
> write one. The glue, `phase_path.py`, writes no entry of its own.

> **Normative.** Acting and the message writes write no entry: their effect records and
> decisions already say what they did (ADR-0306 §5).

> **Normative.** Every emitter takes its sink from the composition root, as `None` where
> `diagnostic_record` is false.

### 5. Planning's thinking

> **Normative.** Where the record is on, `PydanticAIToolCallingCompleter` is handed a
> `DiagnosticSink`. It asks the provider to return its thinking's text where the provider
> otherwise omits it, as Anthropic's adaptive thinking does without a summarised display;
> where the record is off, the request is as it is without this decision.

> **Normative.** The completer writes planning's returned entry from the provider's
> response, whether or not the response reads as a round, before it returns or raises.
> Where no response came back, planning's module writes the returned entry, with the
> failure.

> **Normative.** The thinking reaches the record and nothing else. `RoundResponse`, the
> episode and the next round never carry it (ADR-0307 §2:1, §2:6).

> **Normative.** `core` gains a module carrying the activation an entry is written for,
> outside every signature, as `core/correlation.py` carries ADR-0119 §4's identifier.
> `orchestration` binds it for the whole of an activation's run, and only there; the
> completer reads it, and writes nothing where none is bound.

A recorded summary is the provider's summary of its thinking, not the thinking itself.
That is what the provider returns, and the record keeps what came back.

### 6. The file and its bounds

> **Normative.** The record is the directory `diagnostics` in `Settings.data_dir`, and
> each activation's entries are one file in it, named by the activation's id with the
> suffix `.jsonl`. The store refuses to write a file for an id that is not a plain file
> name.

> **Normative.** Each entry is one line holding one JSON object: the activation's id, the
> source, whether it is given, returned or a step, the instant it was written, and its
> body. Entries are appended in the order they are written, and each line lands whole.

> **Normative.** A file holds at most `DIAGNOSTIC_FILE_BYTES`, a composition-root
> constant of 8 MiB. An entry that would take a file past it is not written; one last
> line marks the file truncated and when, and nothing more is written to it.

A busy activation is far below 8 MiB: six planning rounds of a few tens of kilobytes, and
digests whose parts are at most `PHASES_DIGEST_PART_CHARS` each. The cap stops one
runaway activation from filling the disk; the window bounds the rest.

### 7. Retention, backup, deletion and forgetting

> **Normative.** `Settings` gains `diagnostic_retention`, a duration that is finite and
> strictly positive, with no spelling for keep forever. Its default is 30 days.

> **Normative.** `DiagnosticRetention.purge_before` deletes every file in the record
> whose last write is older than the instant. The engine calls it with the instant
> `diagnostic_retention` before now, beside the trace store's purge in the one sweep
> ADR-0119 §10 wires behind the retention purge job, and `Engine._purge_expired` remains
> the only place a purge is called.

> **Normative.** The sweep runs whatever `diagnostic_record` says, so files written while
> it was on are still deleted after it is turned off.

> **Normative.** Where `retention_purge_interval` is disabled, the hub refuses to start
> while `diagnostic_record` is true or the record's directory holds a file, before the
> API accepts a request, naming the directory. It reads the directory's listing and no
> entry.

> **Normative.** A backup excludes the record's directory and every file beneath it. Its
> path comes from the composition root, where the store is created (ADR-0123 §3:3).

> **Normative.** Deleting the owner's data destroys the record with everything else in
> the data directory (ADR-0126 §1:2).

> **Normative.** Forgetting a record, a conversation or a story does not reach the
> diagnostic record; the window is its forgetting. A forgetting design that lands later
> covers it, or states that the window remains its forgetting.

A backup is left without it because a backup outlives the window: an artifact holding the
record would keep raw outside text that the window exists to delete, beyond anything a
sweep can reach.

### 8. The code it binds

| Code | Change |
| --- | --- |
| `DiagnosticSource` | New closed enumeration, added to and never renamed: `controller`, `understanding`, `recall`, `planning`, `authorizing`, `digesting` |
| `DiagnosticKind` | New closed enumeration: `given`, `returned`, `step` |
| `DiagnosticEntry` | New frozen record: `activation_id: Identifier`, `source: DiagnosticSource`, `kind: DiagnosticKind`, `recorded_at: UtcInstant`, `body: FrozenJsonMapping` |
| `DiagnosticSink` | New Protocol: `async write(entry: DiagnosticEntry) -> None`, which raises nothing but an external cancellation (§2:4–§2:5) |
| `DiagnosticRetention` | New Protocol: `async purge_before(instant: UtcInstant) -> int`, the number of files deleted |
| `core/diagnostics.py` | New module: binding the activation for a run, and reading it (§5:4) |
| `Settings` | Gains `diagnostic_record` and `diagnostic_retention` |
| The hub's startup | The refusal of §7:4 |
| `evaluation/` | The store, implementing both Protocols, and their canonical fakes and conformance suites as a triad |
| `PydanticAIToolCallingCompleter` | Takes a `DiagnosticSink` or `None`, asks for the thinking's text where it has one, and writes planning's returned entry (§5) |
| The controller and the phase modules | Each writes §4's entries; `read_outside_content` gives the grounds that held |
| `Engine._purge_expired`, `PurgeReport` | One more purge, and its count; the composition test's sweep guard gains its line |
| The backup | Excludes the record's directory (§7:5) |
| `ToolCallingCompleter`, `ModelProvider`, `RoundResponse`, `EvaluationTrace`, the trace Protocols | Unchanged |

> **Normative.** The `core` types, Protocols and module the table names are added as it
> states, and no shape the wire carries changes.

### 9. Relationship to earlier decisions

| Earlier decision | What changes |
| --- | --- |
| ADR-0004 §1, §4, §5 | Nothing: the record is Tier 1, owner-only on disk, and never logged |
| ADR-0004 §6 | The view and export limbs, only as they reach the record: no surface shows it and no export carries it, and the owner reads and copies its files on the server. The deletion limb binds entire (§7:6), and the window answers the retention limb |
| ADR-0060 | Nothing: a write re-raises an external cancellation (§2:5) |
| ADR-0119 §2, §7:3, §11 | Nothing: no trace carries content, nothing reads a trace back, and the record is neither a trace nor in the trace store |
| ADR-0119 §10 | Nothing: the record's sweep runs in the one sweep, as the trace store's does |
| ADR-0123 §3:1, §3:4 | The exclusions gain the record's directory, and every file beneath it is excluded rather than a file matched exactly (§7:5) |
| ADR-0126 §1:2 | Nothing: deleting the owner's data destroys the record |
| ADR-0306 §5 | Nothing: acting and the message writes are recorded by their effect records |
| ADR-0307 §2:1, §2:6 | Nothing: the thinking is none of the round's parts and never reaches the next round |
| ADR-0308 §6:4 | *And go when the activation ends*, for the copy of a held result's text that a digest's prompt carries into the record; the held results themselves still go, and are never saved with the episode |
| ADR-0308 §6:5 | Nothing: digesting alone reads the held results, and the record is not a stage |

> **Normative.** This numbered draft records its replacements on the status lines and in
> a dated header note of ADR-0004, ADR-0308 and ADR-0123, atomically with this ADR under ADR-0070
> and ADR-0082, preserving their ratified bodies. The replacements take effect on this
> ADR's ratification.

## Consequences

**What becomes possible.**
- A QA run, or a real day's use, can be diagnosed from what each phase was actually shown
  and actually said, planning's thinking included, rather than from the code.
- The owner can see which records made an activation count as having read outside
  content.

**What it costs.**
- Where it is on, the data directory holds raw outside text and other people's words for
  up to the window, outside every forgetting but the window's.
- Each entry is a file append on the activation's path, and planning's request asks for
  the provider's summarised thinking.
- Restoring a backup brings back no diagnostic record.

**What stays open.**
- Whether the learning design wants reasoning traces from real use, which would change
  what is kept and for how long (#2863).
- How a forgetting design covers the record (§7:7).

## Alternatives considered

- **A trace kind, or a table in the trace store.** Rejected: a trace never contains what
  it is about (ADR-0119 §2), and the two differ in tier and lifetime.
- **The episode.** Rejected: episodes are read back, and this record is safe only
  because nothing reads it.
- **The log.** Rejected: logs are Tier 2 only (ADR-0004 §5).
- **Planning returning its thinking on `RoundResponse`.** Rejected: it would make the
  thinking a fifth part of the round (ADR-0307 §2:1) and put it where planning could read
  it.
- **Passing the activation into `ToolCallingCompleter.respond`.** Rejected: it would put a
  diagnostic concern into a contract every implementation and fake carries, which is
  ADR-0119 §4's ground for an ambient carrier.
- **One database for the record.** Not chosen: a file per activation is read with the
  server's own tools and swept by deleting it, with no schema to migrate.
- **Test hubs only.** Rejected by the owner: real use is where the undiagnosable failures
  happen (#2863).
- **Keeping only a digest's reply, not the raw outside text.** Rejected by the owner: the
  text is what shows whether a digest missed or misread.
- **Leaving the record in backups.** Rejected: the window could not then be its
  forgetting.
