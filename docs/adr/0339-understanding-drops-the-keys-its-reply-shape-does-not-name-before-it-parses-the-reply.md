# 339. Understanding drops the keys its reply shape does not name before it parses the reply

- Status: Partially superseded by ADR-0354 (§2:1–§2:6 and §4:1–§4:2, for a reply understanding receives as a structured call) and ADR-0353 (§2:2, whole; §2:1's *The elements of `answers` never reach the drop, by the next clause*: the drop applies to every reply)
- Date: 2026-10-21
- Scope: how the understanding stage reads one completion's reply before ADR-0276 §6:2's checks run, and what it logs about that reading. The problem is [#3246](https://github.com/leonapivato/ai-assistant/issues/3246), and the clauses that make it a decision were found by the stop recorded on it ([comment](https://github.com/leonapivato/ai-assistant/issues/3246#issuecomment-6308698408)). Schema-constrained output, #3246's second option, and the other three stages' readers are not decided here (§5).
- Dependency: [ADR-0276](0276-an-activation-is-understood-before-it-is-associated-and-the-understanding-is-retained-with-its-episode.md), as its status line leaves it.
- Authorization: the owner, 2026-10-21: "Dont draw the line who ratifies what, Ill just check in and if I see something wrong I'll give input to you". Under that standing delegation the decision is the dispatcher's, the dispatcher assigned 0339, and the dispatcher ratifies it.
- **Changes no contract.** No type in `core/types.py` changes, no Protocol changes, nothing the wire carries or a record stores changes, and `PROTOCOL_VERSION` does not move. It amends two clauses of a contract-surface decision, so both review lenses run on it.
- **Partially supersedes**, in the clauses §6's first table names: ADR-0276.
- Partially superseded: 2026-10-27 by ADR-0354 — §2:1–§2:6 and §4:1–§4:2, for a reply understanding receives as a structured call: nothing is dropped from it and no count is logged, because the schema it is sent is closed and the reply is read by one rule (ADR-0354 §3:2, §3:4, §10:1). Every other clause stands. This replacement takes effect on ratification of ADR-0354. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-27 by ADR-0353 — §2:2, whole, and §2:1's *The elements of `answers` never reach the drop, by the next clause*: the reply carries no answer, and the drop applies to every reply on the text path, `answers` included (ADR-0353 §9:14). Every other clause stands. This replacement takes effect on ratification of ADR-0353. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.

## Context

**What happens.** The understanding stage makes one completion and validates it in the order
ADR-0276 §6:2 sets. The first check is that "the output parses as one
`ProposedActivationUnderstanding`". ADR-0276 §2:1 makes every model of that shape a frozen
pydantic model with `extra="forbid"`, so a reply carrying any key the shape does not name fails
that check. A failed parse costs the one repair completion §6:2 allows. If the repaired reply
fails the parse too, §6:3 raises `UnderstandingError` and the activation ends as a failure.

**The evidence.** On 2026-10-21 the first real run of ADR-0337's regression suite lost a
candidate sample on the case `prompt_cases/understanding/label-in-meaning`. The reply carried a
stray `"meaning_grounds"` beside the `"meaning_ground"` the shape names. Everything the stage
reads was present and well formed. The reply was refused for a key nobody asked for.

**What the tree holds.** These facts hold on the tree this decision was written against:

- `_parsed` in `orchestration/understanding.py` removes one enclosing Markdown code fence,
  which its docstring calls "a deterministic, code-owned normalization of a wrapper, not a
  repair of the object inside it", and then validates the body as one
  `ProposedActivationUnderstanding` with pydantic's `model_validate_json`. Any `ValidationError`, `ValueError` or
  `RecursionError` makes it return `None`, which `UnderstandingStage._validated` reports as the
  reason `unparseable`.
- The shape's models are `ProposedActivationUnderstanding` and the four it holds in sequences:
  `ProposedReference`, `ProposedRelationship`, `UnresolvedMatter` and `ProposedAnswer`. Each is
  `ConfigDict(frozen=True, extra="forbid")`.
- `UnresolvedMatter` is shared. The recorded `ActivationUnderstanding` holds it too, so a change
  to its configuration would reach a stored record.
- `UnderstandingStage._completed` writes the reply's text to the diagnostic record as the
  model returned it (ADR-0314 §4:1).
- `scripts/prompt_replay.py` reads understanding replies with the stage's own `_parsed`
  (`REPLY_READERS`), so the regression suite reads a reply as the hub does.
- pydantic 2.13 accepts `extra` as an argument to `model_validate_json`. A spike, discarded
  before this draft, showed `extra="ignore"` given there dropping unnamed keys at the top level
  and inside every nested element, while each model keeps its own `extra="forbid"`.

**Why it needs a decision.** ADR-0276 §2:1 and §6:2 together require the refusal. No later
supersession touches either clause. Ignoring an unnamed key therefore changes what a ratified
clause requires. The other three stages that read a JSON reply (digesting, tidy-up and the
matters pass) are in a different position: no ADR requires their refusal, so their readers
change without a decision.

**Where a dropped key would widen authority.** Two of the shape's fields bear on what an
input approves, and both default to something an approval reads. `ProposedAnswer.parts`
defaults to `()`, and an empty `parts` approves every part the question showed (ADR-0321
§3:6, ADR-0322 §2:4); the authorizer reads it that way. The matters in `unresolved` are what
`_fits_several` reads to record no pointer for a yes that could fit more than one question
(ADR-0321 §3:5, ADR-0322 §2:3). So a reply writing `"part"` for `"parts"`, or
`"unresolved_matters"` for `"unresolved"`, beside an answer is refused today and repaired.
With its keys dropped it would parse as a yes to every part, or as a yes no matter guards.
Both fields bear on authority only where the reply proposes an answer. Without an answer,
neither reaches an approval.

**Why the guard reads the reply, not the call.** The regression suite reads a reply with the
stage's own reader, which takes the reply's text and nothing else (`REPLY_READERS` in
`scripts/prompt_replay.py`). A rule that depended on what the call rendered, such as whether
it showed a question, would give that reader no way to decide, and the suite would pass
replies the hub refuses. A rule decided from the reply's own text keeps one reader for both.

**Why logging needs a decision too.** ADR-0276 §6:7 says the stage "logs stage and code-owned
reason only". A count is neither, so a log line carrying one is an addition to that clause. The
same clause forbids logging model output. A key the model wrote is model output, so the names
of the dropped keys cannot be logged.

## Decision

We will make the understanding stage drop every key its reply shape does not name, at every
depth, before the parse ADR-0276 §6:2 requires, unless the reply proposes an answer. A reply
that proposes one parses exactly as it does today. The types keep `extra="forbid"`. Every check
after the parse, and the one repair completion, stay as they are. The stage logs how many keys
it dropped, and never which.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the authorization to
> ratify stands. An assigned number or a green review alone does not change its status.

> **Normative.** No lane implements this decision before it merges `Accepted` (golden rule 5,
> ADR-0015 §5).

> **Normative.** This decision binds the understanding stage's reading of its own replies, the
> first completion's and the repair's, and no other stage's.

### 2. The drop

> **Normative.** Before the parse, after the enclosing code fence is removed, the stage drops
> every key the reply shape does not name. The reply shape is `ProposedActivationUnderstanding`
> and every model it holds, as `core/types.py` defines them when the reply is read. The drop
> applies at every position where the shape expects one of its models: the reply's top level,
> and each element of every sequence of models, today `references`, `relationships` and
> `unresolved`. The elements of `answers` never reach the drop, by the next clause.

> **Normative.** The drop applies only to a reply that proposes no answer. Where the reply's top
> level holds the key `answers`, unless every value it holds under that key is an empty JSON
> array, the stage drops nothing from that reply and parses it exactly as it would without this
> decision. Whether the drop applies is decided from the reply's text alone, separately for the
> first output and for the repair.

> **Normative.** A key is named only where it equals, exactly, the name of a field of the model
> expected at that position. The drop does not fold case, does not map a near-miss onto a
> field, and does not move a key to another position. A key named by a model at another
> position is dropped where it stands.

> **Normative.** A dropped key's value is never read, validated or examined. The drop changes no
> value it keeps. At a position where the shape expects a model and the reply holds something
> other than a JSON object, or where a sequence holds an element that is not one, the drop does
> nothing, and the parse judges what is there.

> **Normative.** A reply holding no key the shape does not name parses exactly as it would
> without this decision: the same reply is accepted as the same proposal, and the same reply is
> refused. A reply the drop applies to that holds such keys parses exactly as the same reply
> would with those keys and their values removed.

> **Normative.** A reply the drop applies to whose only defect is keys the shape does not name
> is a parsed output.
> It costs no repair completion and is not a parse failure. A reply that still fails to parse
> once the keys are dropped is a parse failure under ADR-0276 §6:2 and §6:3, unchanged.

### 3. What stays as it is

> **Normative.** This decision changes no type. `ProposedActivationUnderstanding`, every model it
> holds, `UnresolvedMatter` included, and the recorded `ActivationUnderstanding` keep
> `extra="forbid"`, so every other reader of those types, a stored record's included, refuses
> an unknown key as before.

> **Normative.** Required fields, field types and every check after the parse in ADR-0276
> §6:2's order run as they stand: the labels resolve under ADR-0276 §3, a `supplied` element names a
> label, and story labels are read as ADR-0300 §6:8 has them. The repair completion still
> follows a genuine parse failure or a label defect, still carries the first output as the
> model returned it, unpruned, and its code-owned statement says nothing about dropped keys.

> **Normative.** A dropped key is not a grounding defect. It is not counted in
> `grounding_dropped`, and nothing a record stores says a key was dropped.

> **Normative.** The drop alters no diagnostic entry. The stage's returned entry keeps the
> reply's text as the model returned it, stray keys included (ADR-0314 §4:1).

### 4. The count

> **Normative.** Where an output parses and the drop removed at least one key from it, the stage
> logs one line for that output carrying the stage, a code-owned reason and the number of keys
> the drop removed, counted across every depth. An output from which nothing was dropped, and
> an output that does not parse, log no such line.

> **Normative.** The line carries no key name, no value, no position and no other text taken
> from the reply. The number is computed by code. ADR-0276 §6:7's rule against logging input,
> window content, model output and exception content binds the line in full.

### 5. Delivery, and what is not decided

> **Normative.** The implementation is one lane, scoped to `orchestration/understanding.py` and
> its tests. It changes no file in `core/`.

The cut, for the dispatcher. The lane changes the stage's reader and adds the log line. The
method is the lane's: pydantic's validation-time `extra` override is one way, a walk of the
decoded object against the shape is another, and §2:5 is the test either must pass. Two
constraints come from the tree. First, the drop belongs in the reader `scripts/prompt_replay.py`
already imports as `understanding_parsed`, so the regression suite reads a reply as the stage
does and no script changes. Second, that reader keeps its signature, `(str) ->
ProposedActivationUnderstanding | None`, so the count reaches the stage some other way and the
lane stays inside `orchestration/`. The lane's tests cover a stray key at the top level and in
each sequence's element, a near-miss of a required field (which still fails and repairs), a
non-object element, the unchanged diagnostic entry, and the log line's fields. They also cover
a reply proposing an answer: a two-part question approved in part, with `"part"` written for
`"parts"`, is still refused and repaired, and so is `"unresolved_matters"` beside an answer.
Because the guard reads the reply alone, the suite's reader and the stage's agree on each of
these with no script change.

Not decided here:

- **Schema-constrained output**, #3246's second option: the models layer asks the provider for
  the shape itself. That is a later design, and it would change `models/`.
- **The other three stages' readers.** Digesting, tidy-up and the matters pass are a separate
  lane's, under no ADR, because none requires their refusal.
- **The prompt.** What ADR-0276 §6:1 instructs the model to produce is unchanged, and so is the
  template ADR-0334 loads.

### 6. Relationship to earlier decisions

Superseded in part; every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0276 | §6:2's first check, in the addition alone: on a reply proposing no answer, the keys the reply shape does not name are dropped at every depth before the output is parsed as one `ProposedActivationUnderstanding`, and a reply refused only for them is a parsed output. §6:7's *stage and code-owned reason only*, in the addition alone: a code-owned count of the keys dropped | §2:1–§2:6, §4:1–§4:2 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0276 §2:1 | Nothing: the types keep `extra="forbid"` and the tables keep their complete field sets (§3:1) |
| ADR-0276 §6:1, §6:3–§6:6 | Nothing: the instruction, the failure on a second unparseable output, the recording of a label defect, a successful understanding and `understanding_failed` stand |
| ADR-0275 §8:12 | Nothing: §6:7 applies its rule to the stage, and the count is code-owned |
| ADR-0300 §6:8 | Nothing: story labels are checked as it rules, on the parsed output |
| ADR-0321 §3:5–§3:6, ADR-0322 §2:3–§2:4 | Nothing: a reply proposing an answer is parsed as before (§2:2), so no dropped key reaches an answer pointer or the matters that guard one |
| ADR-0314 §4:1 | Nothing: the returned entry keeps the reply as the model returned it (§3:4) |
| ADR-0337 | Nothing: the suite reads understanding replies with the stage's reader, so after the implementation it reads them with the drop |

> **Normative.** This decision records its replacements on ADR-0276's status line and in a dated
> header note there, atomically with this ADR under ADR-0070 and ADR-0082, preserving its
> ratified body. The replacements take effect on this ADR's ratification.

## Consequences

**Easier.** A reply that says everything the stage reads, plus a key nobody asked for, is read.
The evidence case parses on the first completion. The repair completion is spent on defects the
stage can name, and an activation is no longer failed for a stray key twice over.

**Harder.** A reply proposing an answer gains nothing: a stray key there still costs the
repair, or the reply. That is the price of keeping a malformed answer from reading as a wider
yes (Context). A reply writing `"answer"` for `"answers"` proposes no answer by that rule, so
its keys are dropped and it records no pointer. The yes is lost, not widened: what it would
have approved still waits for a yes.

On every other reply, a misspelt optional field is lost without a repair. A reply writing
`story_label` for `story_labels` parses with no story links. One writing `meaning_label` for
`meaning_labels` loses its labels, though §6:2's check that a `supplied` meaning names a label
still catches a `supplied` one. A misspelt `unresolved` loses matters planning would have
read. A misspelt required field still fails the parse and repairs. What stays silent is an
optional field whose absence is itself valid. Two things show it: the log line's count, and the
diagnostic record, which keeps the reply as the model wrote it.

A code check the suite runs through the stage's reader no longer sees an unknown key, because
that reader drops it. A check for one, ADR-0337's example of "an unknown key absent", has to
read the raw reply.

**Revisit when** schema-constrained output is decided: a provider that returns the shape itself
makes the drop dead code, and the decision that adopts it says whether the drop stays as a
guard. Revisit as well if the log's count shows a misspelling recurring often enough that a
repair for it would be worth its completion.

## Alternatives considered

- **Make the reply's types `extra="ignore"`**, as #3220 did for the observer's own shapes.
  Rejected: it replaces ADR-0276 §2:1's type rule rather than adding to the reader. It reaches
  the recorded `ActivationUnderstanding` through the shared `UnresolvedMatter`, so a stored
  record with an unknown key would load silently. And it changes `core/types.py`, which golden
  rule 5 makes a contract change.
- **Drop on every reply, and refuse only inside an answer element.** Rejected: an answer's
  guard is not inside the element. `"unresolved_matters"` at the top level would be dropped
  and leave a yes no matter guards (Context).
- **Leave strict every call that rendered a question.** It would also keep a misspelt
  `"answers"` refused and repaired. Rejected: the reader would need to know what the call
  rendered, which the suite's reader is not given, so the suite would pass replies the hub
  refuses (Context).
- **Drop on every call, and refuse where a field whose default widens authority is absent.**
  Rejected: it needs a list of such fields that a later field could silently miss, and
  `unresolved`'s empty default is not wrong in itself.
- **Keep the refusal** and let the repair completion handle stray keys. Rejected: the
  evidence shows the refusal spending the repair, or losing the reply, on content the shape
  never asked for.
- **Map a near-miss key onto the field it resembles.** Rejected: guessing what the model meant
  authors content in the model's name. A misspelt required field still fails the parse and is
  repaired from the model's own second reply.
- **Log the dropped keys' names.** Rejected: a key the model wrote is model output, and
  ADR-0276 §6:7 forbids logging it. The diagnostic record already keeps the reply whole for
  whoever needs the names.
- **Record the count on `ActivationUnderstanding`.** Rejected: it is a type change, and the
  record would then carry a fact about the model's formatting rather than about the input.
- **Schema-constrained output now.** Not rejected; deferred (§5). It is a models-layer change
  and a design of its own, and the drop is useful whichever way that design goes.
