# `benchmarks/` — offline evaluation tooling

Developer tooling that drives `ai_assistant` from outside the package. It ships in no
wheel, nothing under `src/` imports it, and it holds no product code. The shape is the
one `scripts/` established — a top-level tree outside `src/`, inside `mypy`'s `files`
— with one difference that motivates the whole placement: this is the first non-`src`
tree that *consumes the library*, so it imports `ai_assistant` exactly as an external
application would and leaves every `lint-imports` contract untouched.

Golden rule 4 still binds here. `lint-imports` cannot see this tree (its
`root_package` is `ai_assistant`), so `tests/benchmarks/test_import_discipline.py`
parses every module and fails on a provider-SDK import.

## `benchmarks/memory` — the LoCoMo / LongMemEval harness

Built for the pilot pre-registered in **issue #1029**. Read that issue before running
anything: it holds the predictions, the decision rule, and the ground rules.

**Ground rule 1 is the one this harness enforces mechanically.** The pre-registration
is finalised by the owner *before* any scored evaluation; until then only smoke runs —
a handful of questions, to validate plumbing — are permitted, and their outputs are not
read as scores. So:

- every run is `RunMode.SMOKE` unless `--mode scored` is asked for;
- a scored run is refused unless `--preregistration-final` is also passed;
- and refused again unless the rest of the configuration makes the word true: whole
  histories (no `--max-sessions`), the on-device embedder, the model judge, and **no
  injected seam** — `execute_run` accepts overrides for the answering, distillation and
  grading seams so tests can drive the pipeline without a model call, and the manifest
  records the *configured* routes, which an override makes false. A scored run builds
  all three from `Settings`. Each of those would otherwise produce artifacts labelled
  `scored` that measure something else;
- the gate runs at `execute_run`, the boundary that writes the manifest, as well as at
  the command line, so a caller reaching the API directly cannot skip it;
- the mode is written into every run's `manifest.json`.

"Has a scored run happened?" is therefore a question about files on disk.

### Commands

```bash
uv run python -m benchmarks.memory corpora            # provenance: source, revision, licence
uv run python -m benchmarks.memory fetch locomo       # download + verify against the pinned digest
uv run python -m benchmarks.memory plan locomo        # what a run would cost — contacts nothing
uv run python -m benchmarks.memory run locomo         # smoke: 5 questions, offline grader
```

Two levers narrow a run, and they are not the same lever. `--limit` bounds **how many
questions** are asked — a smaller sample of the same experiment. `--max-sessions`
bounds **how much conversation** is ingested first, which is a *different* memory and
therefore a different experiment: it is a plumbing lever for keeping a live smoke run
to cents, never a measurement one. A scored run refuses it outright, and every run
records it in the manifest.

`plan` is the one to run before spending. It reports cases, questions, captured turns
and model calls split by what makes them, and warns when the configuration will
quietly distort what is measured.

### Configuration a scored run needs

Read through `ai_assistant.core.config.Settings`, as everything in this project is.
Three values decide whether a run measures the system or measures something else, and
all three land in the manifest:

- `ASSISTANT_EMBEDDER` must stay `on-device` — the vendored `bge-small-en-v1.5`
  (ADR-0006 §2, ADR-0024). `hashing` is the non-semantic QA embedder; a run under it
  measures plumbing.
- `ASSISTANT_EPISODE_RETENTION=none`. The harness runs on the **corpus's** clock, so a
  finite horizon expires each session's episodes a horizon after that session's own
  instant — and LoCoMo's dialogues span the better part of a year against a 30-day
  default. `plan` warns when this bites.
- `ASSISTANT_DEFAULT_MODEL`, and `ASSISTANT_OBSERVER_MODEL` if the episodes should be
  distilled through a different route. Both are recorded; a pilot that moved one
  without recording it is uninterpretable.

### Corpora, provenance and licences

`memory/corpora/provenance.py` is the record: source URL, immutable upstream revision,
SHA-256 and licence for every file, with the reasoning. Read it before publishing
anything computed from this data — **LoCoMo is CC BY-NC 4.0**, non-commercial with
attribution; LongMemEval is MIT.

Every file is pinned twice, to a revision *and* to a digest, and verification has no
bypass: a corpus that can move underneath a frozen prediction makes "refuted"
unreadable. Nothing is committed — `.corpora/` and `.runs/` are ignored — which is the
same treatment the vendored embedding model gets under ADR-0024 §4.

**One choice the owner still has to make.** #1029 names "LongMemEval-S" without naming
a variant, and the dataset the paper published is now marked deprecated by its own
author in favour of a cleaned one that removes noisy history sessions. Those are
different corpora and they do not produce the same scores. The harness defaults to the
cleaned variant (`longmemeval`) and keeps the original reachable
(`longmemeval-original`); which one the pre-registration is conditioned on is the
owner's ruling, not the harness's.

### What a run produces

Under `.runs/<run_id>/`:

- `manifest.json` — the configuration, recorded rather than described: mode, corpus
  revision and digests, both prompts, every route, every bound.
- `records.jsonl` — one line per question, appended as it is answered so an
  interrupted run leaves usable records. Each line carries the answer, the grading, the
  retrieved record ids, the corpus's own evidence pointers, and the ADR-0119 retrieval
  telemetry for that answer.
- `cases/<case>/traces.db` — the trace store. Kept; the other databases are removed
  unless `--keep-stores` is passed.

A provider failure on one question is recorded as `ungraded` — keeping the retrieval it
had already made, ids and telemetry intact — and stepped over rather than allowed to end
the run — dying at question 400 of a paid 2,000-question run loses
the rest of the run as well as the rest of that case. A *missing credential* is not
that: it is checked once at startup through `ensure_model_credentials`, so a
misconfiguration fails immediately instead of becoming 2,000 recorded failures.

**Nothing aggregates.** No accuracy, no per-category rate, no verdict against a
prediction — because an aggregate over a smoke run is a score, and ground rule 1 makes
that exactly what must not be produced. Aggregation belongs to whatever reads the JSONL
once the pre-registration is final.

### Threats to validity this harness introduces

#1029 lists the ones inherent to the benchmarks. These are the ones the *harness*
adds, each argued where the code that makes it lives:

- **LoCoMo's photo turns become text.** ~1,200 of its turns carry a caption for a
  shared image; the harness renders them as `[shared a photo: …]`. Dropping them would
  make a slice of questions unanswerable and charge it to retrieval.
- **LoCoMo keeps speaker names in the utterance text; LongMemEval does not.** LoCoMo is
  two named third parties, where the name is evidence; LongMemEval is a real user and a
  real assistant, which map onto the episode's two halves directly.
- **The closing observation window overlaps.** `ObservationStage` reads the most recent
  *N* turns with no offset, so a case whose turn count is not a multiple of the batch
  re-distils a few turns. Counted as `episodes_reobserved`, never hidden.
- **Session instants are read as UTC.** Neither corpus states a zone.
- **The answering prompt names abstention explicitly.** #1029's P7 is a prediction about
  the *pipeline*; a prompt that forbade abstention would confirm it by construction.
