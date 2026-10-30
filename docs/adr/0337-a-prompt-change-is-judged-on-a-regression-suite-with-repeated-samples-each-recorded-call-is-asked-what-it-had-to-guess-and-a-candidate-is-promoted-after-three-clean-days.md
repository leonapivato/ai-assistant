# 337. A prompt change is judged on a regression suite with repeated samples, each recorded call is asked what it had to guess, and a candidate is promoted after three clean days

- Status: Partially superseded by ADR-0354 (§6:3, in the addition alone: a structured call's follow-up is sent with no shape) and ADR-0353 (§9:1 and §4:3, for the understanding default ADR-0353's lane U2 ships alone) and ADR-0356 (§9:1 and §4:3, for the planning default ADR-0356's lane P3 ships alone; §9:1, for understanding's two phrases alone; §6:6's *and nothing else*, in the addition alone)
- Date: 2026-10-21
- Scope: the first, deliberately slim version of a continuing process for improving the hub's prompts on the owner's hub: a regression suite of prompt cases and its runner, repeated samples for the properties that guard the user's authority and memory, a follow-up question asked after a model call both in the replay tool and on the owner's hub, and the rule by which a candidate becomes the default. Everything else the proposal carried is named in §10 as not decided here.
- Dependency: [ADR-0314](0314-a-diagnostic-record-keeps-what-each-phase-was-given-and-returned-and-nothing-reads-it-back.md), [ADR-0316](0316-an-activation-viewer-outside-the-package-shows-the-diagnostic-record-to-the-owner-on-the-server.md), [ADR-0333](0333-the-observer-writes-diagnostic-entries-in-a-file-of-its-own-beside-the-activation-it-learned-from-and-the-viewer-shows-what-was-learned.md), [ADR-0334](0334-a-prompt-is-a-template-the-hub-loads-at-start-the-owners-hub-may-override-it-from-its-data-directory-and-each-model-call-records-the-version-it-sent.md) and [ADR-0335](0335-a-replay-re-sends-recorded-model-calls-from-a-copy-of-the-owners-hub-through-a-candidate-prompt-and-keeps-each-new-reply-beside-the-original.md), as their status lines leave them.
- Authorization: on 2026-10-21 the owner asked to "fix what we've already found. Then lets think about a process so that it can continuously improve over time", and set the posture that "prompt injection and privacy shouldn't be a concern right now since nobody is using it seriously yet." The proposal was draft PR [#3236](https://github.com/leonapivato/ai-assistant/pull/3236). The scope of this version, what it decides and what it defers, is the dispatcher's decision under the owner's standing delegation; the dispatcher assigned 0337 and ratifies it under that delegation.
- **Changes `core`, so it is a contract-surface decision.** `DiagnosticSource` gains one member, `follow_up` (§8:9), and `Settings` gains two fields (§8:1, §8:3). No Protocol changes, nothing the wire carries changes, and `PROTOCOL_VERSION` does not move.
- **Partially supersedes**, in the clauses §11's first table names: ADR-0123, ADR-0314, ADR-0316, ADR-0333, ADR-0334 and ADR-0335.
- Partially superseded: 2026-10-27 by ADR-0354 — §6:3's *the followed call's request as it was sent*, in the addition alone: a follow-up of a structured call is sent through `ModelProvider.complete` with no shape, its followed response being the reply's text as the assistant's turn, so the answer stays text (ADR-0354 §8:8). Every other clause stands. This replacement takes effect on ratification of ADR-0354. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-27 by ADR-0353 — §9:1 and §4:3, for the understanding default ADR-0353's lane U2 ships alone: it becomes the default by U2's reviewed pull request with the re-rendered suite green for it, run with no control under the old default and with no three days as an override first, and once deployed is judged as §9:3 judges a candidate (ADR-0353 §13:5, §13:6). Every other clause stands. This replacement takes effect on ratification of ADR-0353. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-30 by ADR-0356 — §9:1 and §4:3, for the planning default ADR-0356's lane P3 ships alone: it becomes the default by P3's reviewed pull request, judged on the suite with no control (ADR-0356 §11:5, §11:6). §9:1, for understanding's two phrases alone: they become the default by P3's pull request with understanding's suite green against the current default (ADR-0356 §12:2). §6:6's *and nothing else*, in the addition alone: a followed planning response's thinking also reaches the later rounds of its own work (ADR-0356 §13:4). Every other clause stands. This replacement takes effect on ratification of ADR-0356. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.

## Context

**Where this comes from.** On 2026-10-20 and 21 the owner and the dispatcher read the hub's
activations in the viewer, an agent reviewed sixteen dry-run activations against the ratified
rules, replays asked the scout and commit models what had been unclear, A/B replays judged
draft understanding and planning prompts against the recorded control, and a rerun of the
learner with draft prompts showed wins and one regression. That loop found real defects. The
first half of the owner's request, fixing them, is the prompt revision work and does not wait
on this decision. This decision is the second half, cut to what can be built and trusted first.

**What the loop found**, summarised without names because the repository is public:

- **Failures code can see:** a whole reply refused for one stray key; calls a repair had to
  rescue; rounds that only said nothing; approved-action rounds missing the prompt cache
  ([#3223](https://github.com/leonapivato/ai-assistant/issues/3223)).
- **Failures only reading finds:** a greeting answered with an unrequested recap of old
  matters; prompt labels such as `H8` leaking into free text and from there into stored notes;
  an approval the system's policy asked for, learned as the user's habit; "waits for your yes"
  said with no question asked ([#3104](https://github.com/leonapivato/ai-assistant/issues/3104));
  a compound claim marked as backed "as worded" by a part stating only one clause; details
  invented from the data; a fact lost from current memory when a narrower memory replaced a
  broader one.
- **Defects that were not the prompt's:** stale labels inside past readings, an unmarked
  newest-first order, the hub's time zone left at UTC, strict parsing of keys nothing reads.
  A prompt change would only have hidden them, so routing a failure to the right fix comes
  before drafting anything.

**What one sample cannot tell.** In the 2026-10-21 A/B replay the hub's own run of an
activation asked for approval and the recorded control replay of the same prompt did not. One
sample per candidate cannot tell a fix from noise on a property like that, and ADR-0335 §4:10
sends each call once for each candidate.

**What the calls said about themselves.** Asked after the fact what had been unclear, the scout
and commit models named the same real gaps from one call to the next: undefined fields, rules
that conflict, a setting they had to assume. The script that asked them dropped planning's
tools, and the model then complained, wrongly, that they were never described. The owner
suggested asking "the model after it completes the first answer."

**What already exists.** Every prompt is a template the owner's hub may override from its data
directory, each given entry records the prompt's name, version and origin, and promotion is a
reviewed pull request (ADR-0334). `scripts/prompt_replay.py` copies the owner's hub's data
directory on its server and re-sends recorded calls through a candidate, once each, under a
bound of 100 calls (ADR-0335). The diagnostic record is write-only: nothing in `ai_assistant`
reads an entry back and no entry's body reaches a prompt (ADR-0314 §3:1, §3:2).

**The posture.** The owner's hub's data is working material for improving the hub, and
prompt injection is not a design constraint here. What stays costs nothing now and would be
expensive to add back: no record text in the repository or in a shipped default, nothing
placed or promoted automatically, and no hosted family hub's data used without consent. Where
this decision keeps real data on the server, it is because ADR-0314 §3:4 and ADR-0335 §3:5
already put it there, not because it adds a guard of its own.

## Decision

We will keep a regression suite of prompt cases, synthetic ones in the repository and real
ones in a case store on the owner's hub's server, run by a further command of the replay tool;
send each case and each replayed call several times where a property guards the user's
authority or memory; ask a fixed follow-up question after a model call, in the replay tool and,
on the owner's hub alone, after every recorded call under a daily budget; and promote a
candidate to the default by a reviewed pull request once the suite is green for it and it has
run clean on the owner's hub for three days. Nothing is placed or promoted automatically.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the authorization to
> ratify stands. An assigned number or a green review alone does not change its status.

> **Normative.** No lane implements this decision before it merges `Accepted`.

> **Normative.** The first lane is the suite's format, its runner and its seed cases (§3, §4),
> and it merges before any other lane of this decision.

### 2. Whose hub, and what stays out of the repository

> **Normative.** Every part of this decision that sends a hub's data to a model, or keeps it,
> does so for the owner's hub alone. Nothing in it runs on, reads or keeps the data of a hub
> hosted for another person under the #879 ruling; doing so takes a decision of its own, made
> after that person has consented.

> **Normative.** No file in the repository, and no shipped default, carries text taken from a
> diagnostic entry, a copy, the case store or any store of a hub. A suite case, a candidate
> template and a promotion pull request are each held to this.

Nothing mechanical enforces the second clause; the review of the pull request that adds the
file reads for it, as the promotion review reads a template against ADR-0334 §6:3.

### 3. The regression suite: its home and its cases

A **case** is one model call and a property its reply must have. A **synthetic** case is
invented; a **real** case is a call the owner's hub made.

> **Normative.** The synthetic cases live in the repository in the directory `prompt_cases/`
> at its root, one file per case under a directory named for the case's prompt, outside the
> `ai_assistant` package and outside `tests/`.

> **Normative.** Every synthetic case is invented. Its people, places, messages and data are
> modelled on no real person, the owner and the people they talk about included.

> **Normative.** A case is one TOML file, read with the standard library's `tomllib`. It names
> its prompt, the flags the prompt is rendered under, its input, its property, its number of
> samples, the failure class it guards and the issue or date it came from, and whether it is a
> development case or a held-out one.

> **Normative.** A case's input is the call's request after the system message: its messages
> and, for a planning call, its offered tools, in the form a given entry records them. It is
> held in the case file, or in a JSON file beside it that the case names.

> **Normative.** A case of the prompt `follow_up` instead holds the followed call's request
> whole, its system message and its offered tools included, and the followed response, so that
> its candidate is rendered as the request's last user message, as §6:3 has the hub send it.
> It is rendered under no flag, since `follow_up` declares none, and the followed call's flags
> are kept with it only as a record of where it came from.

> **Normative.** A case's property is either a code check, named from the closed set the runner
> declares, or `read`, which names what a person reading the reply looks for.

A code check is one code can decide, such as no prompt label in a free-text field, a required
field present, an unknown key absent, a question asked where the round proposes an action that
needs a yes. Everything else is `read` until a judge exists (§10). A held-out case is never
shown to whoever drafts a candidate, so a fix tuned on its own cases is still measured on
others. A rendered request goes stale when the code changes how it renders data, which is the
cost of this input form (§10 keeps the alternatives open).

> **Normative.** The seed cases cover, with at least one synthetic case each, the failure
> classes that reading found on 2026-10-20 and 21: a greeting answered with a recap; a prompt
> label in a claim or a note; an approval learned as the user's habit; "waits for your yes"
> with no question asked; a compound claim backed as worded by a part stating only one clause;
> a detail the parts do not state; and a fact lost from current memory by a narrower write.

> **Normative.** A test in the gate reads every synthetic case and checks its form, its prompt,
> its flags and its code check against what the package and the runner declare, and sends no
> model call. No test in the gate sends a case to a model.

The suite is outside `tests/` because the gate must not spend model calls or turn flaky, and
because ADR-0334 §9:1 keeps wording out of tests. A case asserts what a reply does, never what
an instruction says.

### 4. The runner, and the real half

> **Normative.** The runner is a command of `scripts/prompt_replay.py`, `suite`, and is bound by
> every clause of ADR-0335 that binds the tool except where this section says otherwise.

> **Normative.** A suite run renders from a candidate template each case's system message, or a
> `follow_up` case's last user message (§3:5), as ADR-0335 §4:2–§4:5 have a replay render one,
> under the case's flags, and sends it with the case's input as ADR-0335 §4:6–§4:8 have a
> replay send a recorded call.

> **Normative.** A suite run sends each case under the candidate and under the prompt's
> current default from the checkout the tool runs from, which is the control, unless the
> candidate is that default.

> **Normative.** A suite run counts every call it would make, samples and follow-ups included,
> before it sends anything, and sends none where the count exceeds its bound (ADR-0335 §8:2,
> §8:3).

> **Normative.** A suite run prints, for each case and each version, how many samples passed
> its code check of how many were sent, or that the case is to be read, and prints nothing
> taken from a case's input or a reply.

> **Normative.** A suite run writes each reply, with its case, version, sample and check
> result, to a results file: for a run of synthetic cases alone, in the directory the run
> names; for a run including real cases, in the case store.

> **Normative.** A suite run whose cases are all synthetic reads no data directory, copy,
> record or case store, and may run on any machine, by the owner, the dispatcher or a lane the
> dispatcher briefs.

> **Normative.** The real cases live in one case store: the directory `prompt_cases` in the
> owner's hub's `Settings.data_dir`, created readable by the hub's user alone. The hub reads,
> writes and deletes nothing in it; only the tool's `keep` and `suite` commands, and the
> owner's deleting a case, write there.

> **Normative.** The case store is Tier 1 under ADR-0004 §1 and stays on the owner's hub's
> server: nothing copies it, or anything in it, to another machine, and it is read there, as
> ADR-0314 §3:4 has the record read.

> **Normative.** A command of the tool, `keep`, makes a real case from a given entry in a copy:
> it takes the entry's messages after the system message and its offered tools unchanged, or
> for a `follow_up` case the request whole and the response its returned entry records, and
> the flags as the entry records them or as the owner states them, and writes them with the
> property, samples, class and source the owner gives.

> **Normative.** A real case is kept until the owner deletes it, by a command of the tool or
> by hand. It is not a copy, and ADR-0335 §3:6's deadline does not reach it.

> **Normative.** A pull request carries a real case's results only as counts: its case name,
> its version and how many samples passed.

> **Normative.** A backup excludes the case store's directory and every file beneath it. Its
> name is owned by the composition root, as the record's directory is (ADR-0314 §7:5), and the
> tool and the backup take it from there (ADR-0123 §3:3).

Only the owner, or the dispatcher at the owner's direction, runs a suite over real cases, on the
server, as ADR-0335 §2:4 and §2:5 already have it; §4:7 widens only the synthetic run. A real
case outlives the record's window by design: the failures most worth keeping are the ones the
window would have deleted. The case store sits in the data directory so that deleting the
owner's data destroys it with every other entry there (ADR-0126 §1:2), and it is left out of
backups because a backup may leave the server, which §4:9 forbids (ADR-0123 §3:6). The hub
never writes it, so it is not a store under ADR-0326 §2:2 and owes no migration.

### 5. Repeated samples

> **Normative.** A property is safety-relevant where it is one of: asking before an action
> that needs the user's yes; an approval the system's policy asked for not learned as the
> user's habit; and no fact lost from current memory by a write.

> **Normative.** A case guarding a safety-relevant property declares at least three samples,
> and every other case at least one.

> **Normative.** A suite run sends each case as many times as it declares, under each version
> it runs, and records each response.

> **Normative.** A replay may name a number of samples, and then sends each call that many
> times for each candidate, recording each response; one is the default.

> **Normative.** A safety-relevant property is judged over all of a call's or a case's samples,
> and reported as counts for the candidate and for the control ("asked on 8 of 9, control 5 of
> 9"), never from one sample.

Samples are a count within one run rather than three separate runs: one run is checked against
its bound once, its results are grouped by call, and the viewer shows a call's samples
together. Every sample counts against the run's bound.

### 6. The follow-up question

The **follow-up** is a second request about a call that has completed, asking the model what
it had to guess, what it needed and lacked, and which rules pulled against each other. It
asks after the answer, so it cannot change the answer, and it changes no reply's shape.

> **Normative.** The follow-up's question is a ninth prompt, `follow_up`, whose template is
> ADR-0334's form, shipped beside the module in `models/` that sends it on the hub, and
> overridden on the owner's hub as ADR-0334 §3:3 has any prompt overridden. It declares no flag
> and no value.

> **Normative.** The `follow_up` default asks what the model had to guess, what it needed and
> was not given, and which rules or instructions pulled against each other, and asks it to name
> for each the passage of the instruction or of the data that it is about.

> **Normative.** A follow-up request is the followed call's request as it was sent, its system
> message and its offered tools included, then the followed call's response, then the
> `follow_up` template rendered as one user message.

> **Normative.** Where the followed response proposed calls, the follow-up request closes each
> with a result saying that it was not run because the request is for review only, so that the
> offered tools stay in the request and the conversation stays valid.

> **Normative.** A follow-up's answer is recorded and shown as text. Nothing acts on it, and no
> tool it might propose is run.

> **Normative.** A followed planning response is sent in the follow-up request whole, its
> thinking included, so that the request stays one the provider accepts. That thinking reaches
> the follow-up request, and a real `follow_up` case that keeps it, and nothing else.

One answer on its own is a lead, not a finding: a model explaining itself after the fact
rationalises, and a model asked to complain finds something. What counts is the same complaint
across calls, or a complaint beside a failure found another way.

### 7. The follow-up in the replay tool

> **Normative.** A replay or a suite run may name the follow-up, and then sends it after every
> response the run records, using the `follow_up` default from the package the tool runs from
> or a template file the run names, checked as ADR-0335 §4:3 has every template checked.

> **Normative.** Each follow-up the tool sends carries the request exactly as the response it
> follows was sent, with that sample's own system message, the candidate's or the control's.

> **Normative.** A follow-up the tool sends goes to the run's model through the same path as
> the call it follows (ADR-0335 §4:6–§4:8), and its answer, or its failure, is written into
> that response's result.

### 8. The follow-up on the owner's hub

> **Normative.** `Settings` gains `follow_up_question`, a boolean whose default is false. It is
> true only on the owner's hub; a hub hosted for another person never asks a follow-up.

> **Normative.** Where `follow_up_question` is true and `diagnostic_record` is false, the hub
> refuses to start, before the API accepts a request, naming both settings.

> **Normative.** `Settings` gains `follow_up_daily_calls`, an integer of at least zero whose
> default is 100: the most follow-up calls the hub makes in any 24 hours of one run, counted
> from zero when the hub starts. A follow-up the budget does not admit is not asked, and
> nothing waits for it.

> **Normative.** Where `follow_up_question` is true, the hub asks the follow-up of every
> recorded call, as the budget admits: every model call whose given entry carries `prompt`
> (ADR-0334 §8:2) and whose returned entry holds the model's response rather than a failure
> alone.

> **Normative.** The follow-up asker is a `DiagnosticSink` in `models/` that the composition
> root wraps, where `follow_up_question` is true, around the sink it hands every emitter. It passes each entry on unchanged, pairs
> a recorded call's given entry with the returned entry its source writes for the same call,
> and asks nothing about a call it cannot pair unambiguously.

> **Normative.** The asker reads an entry only as a sink is handed it, and never from a file
> of the record.

> **Normative.** The asker never delays, fails, retries or changes the call it follows or any
> work of the hub: handing it an entry returns once the entry is passed on, and the follow-ups
> are sent off the activation's path, one at a time.

> **Normative.** A follow-up goes to the model that answered the followed call where its
> returned entry names one, and otherwise to the first model of the stage's route, with the
> stage's settings, through `ai_assistant`'s own model layer, and falls back to no other.

> **Normative.** `DiagnosticSource` gains the member `follow_up`. The asker writes, as that
> source and of the kind `returned`, through the sink it wraps, one entry for each follow-up
> it sends, and no given entry.

> **Normative.** A follow-up entry names the given entry it follows by its source, its instant
> and the part or stage its body names, carries the followed call's `prompt` key and the
> `follow_up` template's own, names the model, and holds the answer as text or the failure.

> **Normative.** A call whose given entry was written under several activations (ADR-0333
> §2:9) is asked once, and its follow-up entry written under each of them.

> **Normative.** The store writes an entry whose source is `follow_up` to the file
> `<activation_id>.followup.jsonl` in the record's directory, and nothing the asker writes
> reaches an activation's own file or its observer file.

> **Normative.** A follow-up file is a file of the record like any other: one whole line per
> entry, its own bound and truncation marker, owner-only, swept by its own last write, counted
> by the hub's startup refusal and excluded from backups (ADR-0314 §2:3, §6:2, §6:3, §7:2,
> §7:4, §7:5).

> **Normative.** No follow-up entry's body, and nothing taken from one, reaches a prompt, a
> message, a memory, an episode, a story, a trace or a log; and no decision the hub makes is
> conditioned on one.

> **Normative.** A failure to write a follow-up entry is handled as ADR-0314 §2:4 and §2:5
> have one handled, and no follow-up is retried, whether its call or its write failed.

> **Normative.** A follow-up not sent when the hub stops is not sent; nothing keeps the queue.

> **Normative.** The viewer reads an activation's follow-up file beside its own file, joined
> by name, never lists it as an activation, and shows each answer beside the call it follows,
> one click from that call, off the timeline.

> **Normative.** The replay tool takes no call to replay from a follow-up file.

The follow-up is asked after every recorded call while the prompts settle, so that the
complaints that recur can be told from the ones that do not. Most of each follow-up's input is
the request just sent, so within the provider's cache lifetime it is mostly a cache read;
sending them at once and one at a time keeps them inside it. The asker sits in `models/`
because that is the one layer that sends data to a provider (ADR-0004 §2) and the one that
holds the seam a planning round is re-sent through (ADR-0335 §4:8). Asking a sample instead,
or only beside a detected failure, is the later decision §10 names.

### 9. Promotion

> **Normative.** A candidate becomes a prompt's default only by a reviewed pull request
> (ADR-0334 §7:3), opened once the suite is green for it and it has run clean as an override on
> the owner's hub for at least three days.

> **Normative.** The suite is green for a candidate where, on every case of its prompt, the
> candidate passes at least as many of the case's samples as the current default does, and on
> every case the candidate was written to fix it passes every sample. A sample passes where it
> passes its case's code check, or, for `read`, where the person who read it says it passes.

> **Normative.** A candidate has run clean where, over those days, at least one recorded call
> carries its version, or for a prompt that writes no entries the start's line names it
> (ADR-0334 §8:3), and nobody reading the record, the follow-up answers or the suite has found
> a new failure against that version.

> **Normative.** The promotion pull request states the days the override ran, how many
> recorded calls carry its version, what was read and found, and the suite's results, with
> real cases as counts alone (§4:12).

> **Normative.** The owner's review is not a condition of placing an override or of a
> promotion. Where the owner rules against a candidate at any point, its override is removed,
> or its promotion reverted by a reviewed pull request.

> **Normative.** No tool, timer or automated process places, changes or removes an override.
> Each is the act of the owner, or of the dispatcher at the owner's direction (ADR-0334 §6:1).

> **Normative.** No tool, timer or automated process opens or merges a promotion pull request.
> The dispatcher, or a lane it briefs, opens one, and it merges as every pull request does.

Three days rather than a week: the owner's hub carries a few activations a day, the suite and
the replays carry most of the evidence, and an override can be removed the moment it is found
wanting. Nothing is promoted automatically because an automatic loop optimises what it can
measure rather than what the owner means, because one person's activations are too few to
trust a metric without someone reading the examples (the learner rerun improved every counted
property and still lost a fact), and because a promoted default reaches every hosted hub at its
next deploy (ADR-0334 §6:2).

### 10. What this decision does not decide

| Not decided here | Why it waits |
| --- | --- |
| A timer on the owner's hub, its counts by version and its digest | The suite and the follow-up come first; what a digest should show is better designed once they have shown what recurs |
| A judge model, which model, and how it is calibrated | `read` properties and follow-up answers are read by a person until there is a track record to calibrate a judge against |
| Simulated users and a sandbox hub | A harness of its own, with real models on both sides |
| A scenario library | It feeds the sandbox, and waits with it |
| A confirm or reject control, and a reason on a forget, in the beliefs panel | Interfaces decisions of their own |
| A structured refusal signal in understanding's reply | It changes a reply contract (ADR-0321, ADR-0322) |
| A thinking setting a replay may name (ADR-0335 §4:6) | Model A/B already needs nothing (§4:7); thinking waits for a need |
| A suite case's input as the stage's inputs, or as a scenario | The rendered request is enough to start (§3:4) |
| Asking the follow-up of a sample, or only beside a failure | The every-call stream comes first (§8:4) |
| Using a hosted family hub's data | Consent first, and a decision of its own (§2:1) |

> **Normative.** Each item the table names takes a decision of its own before any lane builds
> it.

### 11. Relationship to earlier decisions

Superseded in part; every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0314 | §3:1, in the addition alone: the follow-up asker reads the entries a sink is handed and decides from them which calls to ask about, and its model calls carry them; §3:2, in the addition alone: a recorded call's request and response reach the follow-up call's prompt and its answer is kept in the record, and a recorded call's request, kept from a copy as a real case, reaches a model in a suite run and its replies are kept in the case store; §4's table, which §4:1 binds, in the addition alone: a row for `follow_up`, which writes a returned entry alone; §5:3, in the addition alone: a planning response's thinking reaches the follow-up request about it, and a real `follow_up` case that keeps it; §6:1, in the addition alone: an activation's follow-up entries are a further file, `<activation_id>.followup.jsonl`; §8:1's `DiagnosticSource` row, in the addition alone: the member `follow_up` | §4:2, §4:10, §6:3, §6:6, §8:4–§8:6, §8:9, §8:12 |
| ADR-0333 | §3:1, in the addition alone: an entry whose source is `follow_up` goes to the follow-up file; §4:1, in the addition alone: the observer's recorded calls are read by the follow-up asker and reach the follow-up call, and a kept observer call reaches a model in a suite run, as for ADR-0314 §3:2; the observer itself still reads no entry | §4:2, §4:10, §8:5, §8:11, §8:12 |
| ADR-0334 | §1:3, in the addition alone: for `follow_up`, the template is the request's last user message, and the system message is the followed call's own; §2:1, in the addition alone: a ninth prompt, `follow_up` | §6:1, §6:3 |
| ADR-0335 | §3:1, in the addition alone: the `keep` and `suite` commands, and the owner's deleting a case, read and write the live data directory's `prompt_cases` directory and nothing else in it; §2:4 and §2:5, in the addition alone: a suite run of synthetic cases alone runs on any machine, by the owner, the dispatcher or a lane the dispatcher briefs; §4:10, in the addition alone: a run sends each call as many times as it names, and may send the follow-up after each response; §6:1 and §6:2, in the addition alone: a result line for each sample, naming its sample, and carrying the follow-up's answer or failure where one was sent | §4:7, §4:8, §4:10, §5:4, §7:1–§7:3 |
| ADR-0123 | §3:1's exclusions, in the addition alone: the case store's directory; §3:4's exact match, for that directory alone, every file beneath which is excluded | §4:13 |
| ADR-0316 | §3:3 and §5:1, each in the addition alone: an activation's follow-up file, read by its name and never listed, with each answer shown beside the call it follows | §8:17 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0314 §2:3, §6:2, §6:3, §7 | Nothing: a follow-up file is owner-only, bounded, swept and excluded from backups as every file of the record is (§8:13) |
| ADR-0314 §3:3 | Nothing: the asker is handed a `DiagnosticSink` as every emitter is, and the store is handed to nothing |
| ADR-0314 §3:4, ADR-0335 §3:5 | Nothing: copies and the case store stay on the server; only a synthetic suite run leaves it, and it reads no hub's data |
| ADR-0335 §3:6 | Nothing: copies are deleted on its deadline; a real case is not a copy (§4:11) |
| ADR-0004 §6, ADR-0126 §1:2 | Nothing: deleting the owner's data destroys the case store with every other entry of the data directory |
| ADR-0326 §2:2 | Nothing: the hub never writes the case store, so it is not a store |
| ADR-0335 §2:6, ADR-0334 §6:2 | Nothing: no hosted hub's data is read, and hosted hubs run the shipped defaults |
| ADR-0334 §6:1, §6:3, §7:1, §7:3, §7:5 | Nothing: overrides are placed by the owner or the dispatcher at the owner's direction, carry no entry text, are held to the ratified clauses, are promoted by a reviewed pull request and are cleared at deploy |
| ADR-0334 §9:1 | Nothing: the suite is outside `tests/`, and a case asserts what a reply does, not what an instruction says |
| ADR-0329 §16:9 | Nothing: follow-ups of the observer's calls count against `follow_up_daily_calls`, not the observer's budget |
| ADR-0004 §2 | Nothing: the follow-up is sent from `models/` to the provider the hub's own call went to |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0123, ADR-0314, ADR-0316, ADR-0333, ADR-0334 and ADR-0335, atomically with
> this ADR under ADR-0070 and ADR-0082, preserving their ratified bodies. The replacements take
> effect on this ADR's ratification.

## Consequences

**What becomes possible.**
- Every failure found becomes a case that every later candidate is run against, so a fix for
  one failure that brings back an old one is caught before it is placed.
- A property that guards the user's authority or memory is judged on a rate over samples,
  against the control's own rate, rather than on one reply.
- Each recorded call on the owner's hub says what it had to guess and what it lacked, read
  beside the call in the viewer, without anyone asking by hand.
- A candidate reaches the defaults on evidence and three days of use, without waiting on the
  owner's reading, and the owner can still stop it at any check-in.

**What it costs.**
- The hub-side follow-up roughly doubles the owner's hub's model calls while it is on, up to
  `follow_up_daily_calls`, most of each one a cache read.
- `read` properties and follow-up answers are read by a person until a judge exists.
- A rendered-request case goes stale when the code changes how it renders data; a stale case
  is rewritten, not trusted.
- A real case keeps raw outside text and other people's words past the record's window, in
  the owner's hub's data directory, until the owner deletes it; a backup restored elsewhere
  brings back no case.
- A promotion without the owner's review rests on the suite, the replays, the three days and
  the promotion review.

**The proposal's open questions.**

| # | Question | Here |
| --- | --- | --- |
| 1 | Judge model | Deferred (§10) |
| 2 | The private case store, and its lifetime | Decided: in the owner's hub's data directory, in no backup, kept until the owner deletes it (§4:8–§4:11, §4:13) |
| 3 | How a case gives its input | Decided: the rendered request (§3:4); the stage's inputs and scenarios deferred (§10) |
| 4 | When an override is settled | Decided: three clean days and a green suite (§9:1–§9:3) |
| 5 | The timer's rhythm | Deferred with the timer (§10) |
| 6 | A "digest ready" message | Deferred with the digest (§10) |
| 7 | The follow-up: where, how often, its budget | Decided: both places, every recorded call, 100 a day (§7, §8) |
| 8 | Repeated samples: n, and which properties | Decided: at least three for the three safety-relevant properties (§5:1, §5:2) |
| 9 | Model and thinking A/B | Model A/B needs nothing; thinking deferred (§10) |
| 10 | Synthetic scenarios: who pays, what bound | Deferred with the sandbox (§10) |
| 11 | A confirm or reject control | Deferred (§10) |
| 12 | A reason on a forget | Deferred (§10) |
| 13 | A structured refusal signal | Deferred (§10) |
| 14 | Seeding first | Decided: the seed lane is first (§1:3, §3:7) |

**Lanes it implies**, each after this merges `Accepted`, the first before the rest (§1:3):
1. The suite: `prompt_cases/` with its seed cases, the gate's form test, and the `suite`
   command with repeated samples over synthetic cases, under `scripts/` and `tests/scripts/`.
2. The case store: its name in `app/` and its backup exclusion in `service/` (ADR-0123 §3:6),
   then `keep` and real-case suite runs in the tool. Seeding the real half is the owner's or
   the dispatcher's act on the server once `keep` exists.
3. Repeated samples and the offline follow-up in `replay`, and the `follow_up` template, with
   the viewer showing a call's samples together.
4. The hub-side follow-up: the `follow_up` member of `DiagnosticSource`, the two settings
   and the startup refusal, the asker in `models/` and its wiring in `app/`, the store's file.
   This changes `core`.
5. The viewer's follow-up display and the replay tool's skip of follow-up files, under
   `scripts/`. The dispatcher may fold this into the fourth.

**What would reopen it.** A suite that stays green while the hub's replies get worse; a
follow-up stream whose answers do not recur and point nowhere; or a candidate that ran three
clean days and then showed a failure the suite had a case for.

## Alternatives considered

- **The proposal's full level two now: a nightly timer, counts by version, a judged sample, a
  digest, and a sandbox with simulated users.** Not chosen for the first version: each needs
  the suite and a judge's track record to be trusted, and the owner asked to fix what was found
  first. §10 keeps each open.
- **Repeated samples as separate runs.** Not chosen: three runs are three bound checks and
  three ungrouped result sets, and the rate a safety property needs is read across them by
  hand.
- **A feedback field in each reply instead of a follow-up.** Not chosen: reflecting in the same
  breath can shift the answer, and the field changes reply shapes that ADR-0276 §2:3, ADR-0307
  §2:1 and ADR-0329 pin.
- **The follow-up built by each stage through a hook of its own.** Not chosen: it needs a new
  Protocol every stage is handed and four stages changed, where every recorded call already
  passes its request and response through one sink the composition root wires.
- **Follow-up entries in the activation's own file.** Not chosen: they are written after the
  activation, days after it for an observer call, and would stretch its timeline and duration.
- **The case store on the dispatcher's machine, or in the repository.** Not chosen: the
  repository is public, and ADR-0314 §3:4 and ADR-0335 §3:5 keep the record and its copies on
  the server; superseding both is not needed for a first version.
- **The case store outside the data directory.** Not chosen: deleting the owner's data
  destroys the data directory and nothing outside it (ADR-0126 §1:4), so a Tier 1 store there
  would escape the delete ADR-0004 §6 grants.
- **Real cases deleted with the copy they came from.** Not chosen: the failures most worth
  keeping as cases are those the window deletes, and the case store holds the owner's hub's
  data on the owner's hub's server.
- **Cases as JSON alone, or as TOML alone.** Not chosen: a synthetic case is written and
  reviewed by hand, which TOML's strings suit; a real case's request is the entry's JSON, and
  the standard library writes no TOML.
- **Automatic placement or promotion.** Rejected (§9).
