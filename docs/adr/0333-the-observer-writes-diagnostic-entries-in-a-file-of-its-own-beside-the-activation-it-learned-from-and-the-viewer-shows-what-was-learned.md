# 333. The observer writes diagnostic entries in a file of its own beside the activation it learned from, and the viewer shows what was learned

- Status: Partially superseded by ADR-0334 (§2's table, in the addition alone: the observer's given entries also carry their prompt's name, version and origin) and ADR-0335 (§4:1, in the addition alone: a recorded observer call's request reaches a model in the owner's replay) and ADR-0337 (§3:1 and §4:1, each in the addition alone: follow-up entries in a file of their own, and the observer's recorded calls read by the follow-up asker and kept as real cases) and ADR-0355 (§2's table, in the addition alone: a structured call's thinking summary)
- Date: 2026-10-20
- Scope: milestone 3, "Learning v1: the observer" (acceptance [#3154](https://github.com/leonapivato/ai-assistant/issues/3154)): what the observer gives [ADR-0314](0314-a-diagnostic-record-keeps-what-each-phase-was-given-and-returned-and-nothing-reads-it-back.md)'s diagnostic record, where those entries live and how they age, and how [ADR-0316](0316-an-activation-viewer-outside-the-package-shows-the-diagnostic-record-to-the-owner-on-the-server.md)'s activation viewer shows them.
- Dependency: ADR-0314, ADR-0316 and ADR-0329, as their status lines leave them.
- Authorization: on 2026-10-20 the owner asked for "something similar to the activation viewer that's also viewing the learning", on the same platform, because the prompts are easier to evaluate "when I see it in action", and agreed the dispatcher's proposal: the same viewer, a learning lane, and a dry run on a copy of the live data before going live. Everything else below is the dispatcher's and this lane's recommendation, not an owner ruling. The dispatcher assigned 0333. The owner reads it before it is ratified (§1:1).
- **Changes `core`, so it is a contract-surface decision.** `DiagnosticSource` gains one member, `observer` (§2:1). No Protocol changes, nothing the wire carries changes, and `PROTOCOL_VERSION` does not move.
- **Partially supersedes**, in the clauses §6's first table names: ADR-0314, ADR-0316 and ADR-0329.
- Partially superseded: 2026-10-20 by ADR-0334 — §2's table, which §2:1 binds, in the addition alone: each given entry the observer writes for a model call also carries `prompt`, the prompt's name, its template's version, and `default` or `override` (ADR-0334 §8:2). Every other clause stands. This replacement takes effect on ratification of ADR-0334. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; the ratified body below is preserved.
- Partially superseded: 2026-10-20 by ADR-0335 — §4:1, in the addition alone: a recorded observer call's request, read from a copy of the owner's hub's record, reaches a model in a replay the owner runs with ADR-0335's tool, and the reply is kept in the copy's record (ADR-0335 §4:1, §6:1); the observer itself still reads no entry. Every other clause stands. This replacement takes effect on ratification of ADR-0335. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-21 by ADR-0337 — §3:1, in the addition alone: an entry whose source is `follow_up` goes to `<activation_id>.followup.jsonl` (ADR-0337 §8:12). §4:1, in the addition alone: the observer's recorded calls are read by the follow-up asker as its sink is handed them and reach the follow-up call, and an observer call kept from a copy as a real case reaches a model in a suite run, as for ADR-0314 §3:2 (ADR-0337 §4:2, §4:10, §8:5, §8:11); the observer itself still reads no entry. Every other clause stands. This replacement takes effect on ratification of ADR-0337. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-28 by ADR-0355 — §2's table, which §2:1 binds, in the addition alone: the returned entry the observer writes for its scout's, framing's and placement's structured calls also carries `thinking`, the provider's summary of its thinking, where the provider gave one (ADR-0355 §5:1, §6:1). Every other clause stands. This replacement takes effect on ratification of ADR-0355. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.

## Context

**The gap.** The observer's two prompts, the scout's and the commit step's, are owed to the
owner's reading (ADR-0329, Consequences), and the owner wants to read them at work. Nothing
shows that work today. The observation record keeps each finding's outcome in the plan
store, by memory ids and operations and with no wording (ADR-0329 §16:1), and a view of
outcomes for the user is a later interfaces decision's (ADR-0329 §18:3). The diagnostic
record has no place for the observer: ADR-0314 §4's table and `DiagnosticSource` close the
list of sources, ADR-0329 leaves "diagnostic entries for the observer's calls" open, and
ADR-0316 leaves open "whether the learning design wants a viewer of its own".

**What there is**, surveyed at `fb3fdf5c`:

- The observer (`orchestration/observer/`, `Observer`) makes one scout call for each
  episode it processes and one commit call for each finding, through
  `ModelProvider.complete` and never through the tool-calling completer. It binds no
  activation (`diagnosed_activation` in `core/diagnostics.py`), so `write_diagnostic`
  writes nothing for it.
- An episode with a processing record names its activation
  (`EpisodeProcessingRecord.activation_id`), canonical UUID4 text (ADR-0275 §6:1). The
  observer skips an episode with no processing record.
- `FileDiagnosticRecord` names each file `<activation_id>.jsonl`, appends under
  `DIAGNOSTIC_FILE_BYTES`, and its sweep deletes a file by its last write
  (`st_mtime_ns`).
- `scripts/activation_viewer.py` lists every `.jsonl` file by its stem as an activation,
  and draws an activation's timeline over the span of its entries' instants.

**Why the timing matters.** An episode is processed once it leaves the episode window
(ADR-0329 §7:1): about ten activations later, and on a quiet hub days or weeks later
(§7:2). An observer entry appended to the activation's own file would restart that file's
window from the observer's write, keeping the activation's raw outside text past the window
the owner agreed for it (ADR-0314 §7:1–§7:2). It would stretch that activation's timeline and
duration in the viewer across those days. And it would land nowhere where the activation's
file had already reached its bound or been swept.

## Decision

We will have the observer, where the record is on, write what each of its model calls was
given and returned and what each finding came to, under the leaving episode's activation
but in a file of its own beside that activation's, so that each file ages from its own last
write. The activation viewer shows those entries as a learning lane on the activation's
page and in a learning overview, read from the record's directory alone.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the owner, having read
> it, has authorized its ratification. An assigned number or a green review alone does not
> change its status.

> **Normative.** One lane implements this decision, after it merges `Accepted` and after the
> lane that wires the observer (ADR-0329 §19's lane 4) has merged: the source, the store's
> second file, the observer's entries and the wiring of its sink, and the viewer's learning
> lane and overview with their tests, in one change. In the same change it makes every step
> on the viewer's timeline clickable where a model call's bar now covers it, which ADR-0316
> §3:3 already requires.

> **Normative.** Nothing in this decision changes what the observer reads, decides or writes
> to the memory store or the plan store.

### 2. What the observer writes

> **Normative.** `DiagnosticSource` gains the member `observer`, and the observer writes, as
> that source, what this section's table gives it, each entry of the kind its column names,
> from its own modules, through the `DiagnosticSink` it is handed.

| Source | Writes | Given | Returned | Step |
| --- | --- | --- | --- | --- |
| Observer | Its modules under `orchestration/observer/` | Each model call's rendered request, naming its step, and the finding for a commit | The model's reply as text, or the failure | The scout's findings as recorded; each finding's outcome; how each attempt ended |

> **Normative.** A given entry is written once the daily budget (ADR-0329 §16:9) admits the
> call and before it is made, and its returned entry once the call returns or fails, as
> ADR-0314 §4:1 has every source write them.

> **Normative.** Every body the observer writes names the leaving episode's id and the
> instant its attempt started.

> **Normative.** The findings entry is written once the scout's findings are recorded. It
> holds each finding's id, its claim, the parts it rests on, the candidate or reliance it
> came from, and how many of the scout's proposals were dropped.

> **Normative.** A finding's outcome entry is written once its commit decides the outcome.
> It holds the finding's id and the outcome as the observation record gives it — the
> policy's ruling, each memory written on with its operations and any track-record entry, or
> why nothing was written — with the words that commit decided for what it wrote: a created
> memory's wording, each support's part, direction and note, and each question's wording.

> **Normative.** An attempt's end entry says how it ended (finished, failed or held) and the
> state it left the episode in, and for a failure its class and its message. An episode
> skipped by rule (ADR-0329 §16:7) is given this entry alone.

> **Normative.** The observer writes entries only where `diagnostic_record` is true: it takes
> its sink from the composition root, as `None` where the setting is false (ADR-0314 §4:4).

> **Normative.** Every entry the observer writes names, as its activation, the activation of
> the leaving episode's processing record. For an episode with no processing record it
> writes nothing.

> **Normative.** Where one scout call reads several due episodes (ADR-0329 §8:3), its given
> and returned entries are written under each of their activations.

> **Normative.** The observer binds no activation (ADR-0314 §5:4). It names the activation on
> each entry itself and stamps the entry from its own clock.

> **Normative.** A failure to write an observer entry never fails, retries, holds or changes
> an attempt or an outcome; it is logged as ADR-0314 §2:4 logs one, and a cancellation
> reaching the write is handled as §2:5 handles one.

Writing an entry about an activation does not make the observer that activation. It
records no episode, links nothing to a story, adds nothing the episode selector reads, and
binds nothing a completer could mistake for an activation's run (ADR-0329 §7:4).

### 3. Its file, and how it ages

> **Normative.** The store writes an entry whose source is `observer` to the file
> `<activation_id>.observer.jsonl` in the record's directory, and every other entry to the
> activation's file that ADR-0314 §6:1 names. Nothing the observer writes reaches the
> activation's own file.

> **Normative.** The observer's file is a file of the record like any other: one whole line
> per entry (ADR-0314 §6:2), its own bound and truncation marker (§6:3), owner-only (§2:3),
> swept by its own last write (§7:2), counted by the hub's startup refusal (§7:4), and
> excluded from backups (§7:5).

An activation id is canonical UUID4 text (ADR-0275 §6:1), so no activation's own file is
ever named like an observer's file.

Because the observer never appends to the activation's file, that file's window still runs
from the activation, as ADR-0314 decided. The observer's file is kept for the window after
the observer last wrote about that activation, a retry or an explicit re-run included.
Either file may outlive the other, and the viewer copes (§5:5). What the observer's entries
quote comes from episodes and memories, which their stores keep anyway, and from the
observer's model replies. The observer reads no held result (ADR-0329 §8:4), so it copies
none of the raw outside text the window exists to delete.

### 4. Write-only, and the logs

> **Normative.** ADR-0314 §3 binds the observer's entries whole. The observer reads no entry,
> its own included, to decide, resume or retry anything, and no observer entry's body
> reaches a prompt, a message, a memory, an episode, a story, a trace or a log.

> **Normative.** The observer's logs stay as ADR-0329 §15:7 has them. The one line this
> decision adds is ADR-0314 §2:4's line for an entry not written, naming the activation, the
> source and the failure's class.

An activation id is minted by the hub (ADR-0275 §6:1) and carries no personal data, so that
line keeps §15:7. The split is the one ADR-0314 already draws: the log says that the
observer ran, at which stage, with counts and code-owned reasons; the entry says what it was
shown, what it answered and what it wrote.

### 5. The learning lane and the learning overview

> **Normative.** The viewer reads an activation's observer file beside its own file, joined
> by name from the directory's listing. It reads neither the plan store nor the memory store,
> nor anything outside the record's directory.

> **Normative.** An activation's page shows a learning lane: the scout's findings, each
> commit's decision and each finding's outcome, grouped by attempt. Clicking one shows its
> body whole, readable and raw, as ADR-0316 §3:3 has every entry shown.

> **Normative.** The learning lane is drawn over the observer's own instants. It does not
> widen the activation's timeline, its duration, or anything its row in the activation list
> shows (ADR-0316 §3:1–§3:2).

> **Normative.** The viewer shows a learning overview: every activation the record holds an
> observer file for, ordered by that file's latest entry, newest first, each linking to the
> activation's page.

> **Normative.** For each activation, the overview shows its input in short where its own
> file holds it, the state the last attempt left its episode in, any failure, and each
> finding's claim in short with its outcome in short: a memory created, a memory added to, a
> memory ended, marked wrong or replaced, a question raised, a track-record entry, or nothing
> kept and why.

> **Normative.** An activation whose own file is absent — swept, never written, or written
> while the record was off — is shown with its learning lane alone, saying that its own
> record is absent. An observer file is never listed as an activation of its own name.

> **Normative.** ADR-0316 §4 to §6 bind the learning lane and the overview whole: the viewer
> follows observer files as it follows activations' files, and serves, writes, prints and
> renders nothing they forbid.

> **Normative.** The implementing lane's tests build observer files with ADR-0314's own store,
> as ADR-0316 §7:2's test builds activations' files, and cover the learning lane, the
> overview, and an activation shown with its observer file alone.

The outcome rides in an entry, rather than being read from the observation record, because
the viewer stays one standard-library file that reads the record's directory alone (ADR-0316
§2:1–§2:2), and because the plan store keeps no wording.

### 6. Relationship to earlier decisions

Superseded in part; every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0314 | §4's table, which §4:1 binds, in the addition alone: the observer as a source; §6:1, in the addition alone: an activation's observer entries are a second file; §8:1's `DiagnosticSource` row, in the addition alone: the member `observer` | §2:1, §3:1 |
| ADR-0316 | §3:2, in the addition alone: the learning lane; §5:1, in the addition alone: the observer file's name | §5 |
| ADR-0329 | §15:1, in the addition alone: the observer also holds a `DiagnosticSink` or `None` | §2:7 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0314 §2:2–§2:5, §3, §5:4, §7 | Nothing: the record stays opt-in, Tier 1, write-only and swept by age; the observer binds no activation; each file ages by its own last write |
| ADR-0316 §2, §4, §6 | Nothing: one standard-library file reading the record's directory alone, near-live, loopback, read-only |
| ADR-0329 §7:4, §8:4, §15:7 | Nothing: the observer is not an activation, reads no diagnostic entry, and logs as before |
| ADR-0329 §18:3 | Nothing: the viewer is the owner's tool on the server and no surface of the assistant's, and a view of outcomes for the user stays a later interfaces decision's |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0314, ADR-0316 and ADR-0329, atomically with this ADR under
> ADR-0070 and ADR-0082, preserving their ratified bodies. The replacements take effect on
> this ADR's ratification.

## Consequences

**What becomes possible.**
- For each episode the observer learned from, the owner reads the scout's request and reply,
  each commit's request and decision, and what was kept, beside the activation it came
  from; and, in the overview, many episodes' findings and outcomes at once, which is how the
  prompts are evaluated in bulk.
- The dry run the owner agreed — the observer over a copy of the live data directory with
  the record on, read in the viewer before the go-live deploy (ADR-0329 §19) — has something
  to read. How and when it runs is the dispatcher's, outside this decision.

**What it costs.**
- Where the record is on, the observer's entries copy episode text, memories' wordings and
  model replies, outside every forgetting, for the window after the observer last wrote
  about an activation; an explicit re-run restarts that window.
- An activation the observer processed has two files, and the viewer joins them.
- The overview reads the bodies' keys as they are written. A change to them can drop a
  summary without failing the gate; the entry is still shown whole (ADR-0316 §5:2).
- The owner copies the viewer to the server again.

**What stays open.**
- A view of the observer's outcomes, open questions and track record for the user (ADR-0329
  §18:3).

## Alternatives considered

- **Appending to the activation's own file.** Rejected: it restarts that file's window from
  the observer's write, stretches the activation's timeline across days, and loses the
  entries where the file is already at its bound or swept.
- **One file, aged by its first entry or by an instant in its name.** Not chosen: the sweep
  would have to read an entry or parse a name, and ADR-0314 §7:2's rule would change for
  every file.
- **A subdirectory for the observer's files.** Not chosen: the sweep, the startup refusal
  and the store's owner-only directory would each have to reach a second directory, where a
  second name in the one directory needs none of that.
- **A file per run or per attempt.** Not chosen: the viewer would join many files for one
  activation, to save only a re-run's restart of one file's window.
- **Files named by the episode.** Not chosen: the owner reaches the learning from the
  activation, and an episode with a processing record names exactly one.
- **The viewer reading the observation record.** Rejected: it would read outside the
  record's directory, the plan store holds no wording, and the viewer is one
  standard-library file (ADR-0316 §2).
- **A learning viewer of its own.** Not chosen: the owner asked for the same platform, and
  one file is one copy and one tunnel.
- **Writing the observer's calls under an existing source.** Rejected: planning's entries
  would hold calls planning never made, and the viewer could not tell them apart.
- **Binding the leaving activation around the observer's work.** Rejected: ADR-0314 §5:4
  confines the binding to an activation's run, and the observer is not one (ADR-0329 §7:4).
- **Logging the observer's calls.** Rejected: logs are Tier 2 and carry no content (ADR-0004
  §5, ADR-0329 §15:7).
