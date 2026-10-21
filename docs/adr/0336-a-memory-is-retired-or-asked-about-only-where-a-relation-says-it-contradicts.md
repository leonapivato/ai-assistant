# 336. A memory is retired or asked about only where a relation says it contradicts

- Status: Partially superseded by ADR-0345 (§2:1, §3:1–§3:3, §4:1, §5:1 and §7:1, for a placed proposal)
- Date: 2026-10-21
- Scope: the memory write path wherever a conflict set holds a memory in band `ASSERTED` or the proposal is in it. When a reconciler labels the conflict set; what `DefaultMemoryPolicy` supersedes and defers on; what a `SUPERSEDE` retires; which stored memories a deferral names; and where the observer raises its question. The defect and its reproduction are draft PR [#3237](https://github.com/leonapivato/ai-assistant/pull/3237).
- Dependency: ADR-0159, ADR-0171, ADR-0328 and ADR-0329, as their status lines leave them.
- Authorization: the dispatcher assigned 0336 and recommends option A of #3237, with B and C under "Alternatives considered". That recommendation is not an owner ruling. The owner reads this decision before it is ratified (§1:1).
- **Contract-surface decision.** It changes `core/types.py` (`MemoryIngestResult` gains one field, §7) and `core/protocols.py` (`MemoryWriter.ingest`'s documented retirement obligation, §5, and that field's meaning, §7). It adds no Protocol, no method, no parameter and no `ConflictRelation` value. A writer built from the contract as it stands would retire records §5 forbids retiring and would not fill §7's field, so it is a breaking change under golden rule 5, and both review lenses are required.
- **Partially supersedes**, in the clauses §11's first table names: ADR-0038, ADR-0050, ADR-0079, ADR-0159, ADR-0171 and ADR-0329.
- Partially superseded: 2026-10-21 by ADR-0345 — §2:1, §3:1–§3:3, §4:1, §5:1 and §7:1, for a placed proposal alone: a proposal whose producer names how it stands to each stored memory it retrieved invokes no reconciler, is ruled by `DefaultMemoryPolicy`'s admissibility floor and confirmation rule alone, and is written by that placement and the rule that a memory changes only in its own holder's beliefs (ADR-0345 §3–§5). A proposal with no placement is ruled as this decision says. Every other clause stands. This replacement takes effect on ratification of ADR-0345. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.

## Context

### The defect

Every write in this context is one the observer makes, memory's one writer (ADR-0329
§2:1). A finding resting on what the user said is a proposal in band `ASSERTED`. A memory
stored before ADR-0328 stands at inference (ADR-0328 §16:10), so it is in band `DERIVED`,
whoever originally said it.

Three paths of `DefaultMemoryPolicy` in `memory/policy.py` rule on the conflict set, and
the conflict set is whatever a retrieval search scored at or above `conflict_threshold`.
That is similarity, not contradiction (ADR-0038's Context says so in terms).

- **Rule 9** (`_rule_on_assertion`, ADR-0038 §1). An `ASSERTED` proposal whose set holds
  no assertion is ruled `SUPERSEDE` at the best-ranked `DERIVED` or `ATTESTED` member.
  `_retirement_set` in `memory/ingest.py` then ends every other member in that class
  (ADR-0050 §1, ADR-0079 §3). ADR-0171 §2:3 leaves the sweep whole wherever the writer
  holds no labelled contradiction.
- **Rule 8** (ADR-0050 §2). An `ASSERTED` proposal whose set holds an assertion it does
  not verbatim agree with (ADR-0121 §1) is ruled `ASK_USER`, and nothing is written.
- **Rule 6** (ADR-0038 §3, ADR-0159 §4:4). A proposal in another band whose set holds an
  assertion it does not agree with is ruled `ASK_USER` too, unless ADR-0214 §1's agreeing
  arm fires.

For every `ASK_USER`, the observer raises a `policy_ask` question on each id in
`MemoryIngestResult.conflicts` (`_asked` in `orchestration/observer/writing.py`, ADR-0329
§13:1). That is the whole similarity set.

A rerun on a copy of live data on 2026-10-21 produced these shapes, shown here with
invented names:

- "The user's sister is named Mira." ended two broader memories that held her email
  address.
- The address finding that followed met the new assertion, was ruled `ASK_USER`, and so
  the address left current memory.
- An address claim about one person raised questions on another person's memories.
- On an empty store, rule 8 alone turns every second fact about one person into a
  question: "Zeno is my roommate", then "Zeno's address is …".

#3237 carries three `xfail(strict=True)` tests in `tests/memory/test_no_loss_on_supersede.py`
that reproduce the first three shapes over invented records.

### Why no relation reaches this arm

ADR-0159 built the machinery that tells a restatement, an addition and a contradiction
apart, and ADR-0171 narrowed the sweep to labelled contradictions. Neither reaches here.
ADR-0159 §2:2 invokes a reconciler "**exactly when**" the proposal is not asserted and no
member is (`_may_reconcile` in `memory/ingest.py`). On this arm the writer holds no
relations, so ADR-0159 §5's spare of a `RESTATES` or `ADDS` member never applies, and
neither does `_refuse_retiring_a_related_conflict`. ADR-0171 §2 states the consequence:
"Nothing about the asserted path changes."

### Why ADR-0038's chosen error no longer holds

ADR-0038 §2 accepts "false-positive supersession of an inferred record" because "an
inference is derived and re-derivable … if it was in fact still true the same
observations will propose it again". That premise fails twice over.

- A legacy memory's only support is the legacy record. The observer processes an episode
  once, when it leaves the window (ADR-0329 §7:1), and never one from before 2026-10-16
  (§7:5). So nothing re-proposes a legacy memory.
- An observer's inference is proposed from one episode's findings. A false-positive
  supersession of it is recovered only if a later episode happens to show the same thing.

ADR-0038's own "Revisit when" names this case: "when conflict detection becomes
contradiction detection rather than similarity (§2's error choice is then re-argued from a
better signal)". ADR-0050's "Revisit if" names the same for rule 8: "§2's gate could
tighten from 'any asserted conflict' to 'a *contradicting* asserted conflict'". ADR-0159
is that signal.

### What changed since ADR-0159 §2 left the arm out

ADR-0159 §2 gives its reason for excluding the asserted populations as latency: "a model
request inside the ingest lock on the two paths a user waits on — the `learn` and
`answer` direct seams, whose proposals are asserted". Neither seam exists any more, and
these facts hold on the tree this decision was written against:

- `remember` records a candidate and writes no memory. `REMEMBER_RECORDS_CANDIDATES` in
  `app/composition.py` is `True`, and the acting stage is wired with `CandidateCalls`
  (ADR-0329 §2:3, §3:1).
- The one producer on the write stage is the observer (`orchestration/writes.py`'s
  module docstring, ADR-0329 §12:1). It runs without an activation waiting on it
  (ADR-0329 §7:6).
- `RememberCalls`, the interim path ADR-0328 §13 governed, is still in the tree but not
  wired while that constant stands, and ADR-0329 §19:3 forbids deploying a build that
  turns it back on beside the observer. Its proposals stand at inference (origin
  `remembered`), except one carrying a confirmation, which stands at "you confirmed this
  wording" (ADR-0328 §13:3) and which §2 leaves unlabelled.
- Authorizing calls `MemoryPolicy.decide` with an empty conflict set (`orchestration/authorizer.py`),
  so no conflict rule this decision changes runs on a turn.

The other argument ADR-0159 §2 gives, that neither asserted arm "reads a relation", stops
being true under this decision. That is the change.

### Words

- **Labelled**: a conflict-set member the writer holds an ADR-0159 §1:1 relation for.
  Otherwise **unlabelled** (ADR-0159 §1:2).
- **The certain rung**: ADR-0121 §1's `agrees`, which is a `RESTATES` label made with no
  model (ADR-0159 §3:1).
- **The retirement class**: bands `DERIVED` and `ATTESTED` (ADR-0079 §3 and ADR-0092 §4,
  read through ADR-0328 §12).
- **The asserted arm**: `DefaultMemoryPolicy`'s rules for a proposal in band `ASSERTED`.

## Decision

We will label the asserted arm too. A reconciler runs on every admissible ingest that
carries no user confirmation, whoever said what. `DefaultMemoryPolicy` supersedes a
memory, and defers to the user over one, only where the writer labels that memory a
contradiction. A `SUPERSEDE` retires only labelled contradictions beyond its target.
Where nothing is labelled, the proposal is installed beside what it resembles. A
deferral names the assertions it contradicts, and the observer asks about those alone.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the owner, having
> read it, has authorized its ratification. An assigned number or a green review alone
> does not change its status.

> **Normative.** No lane implements against this decision before it merges `Accepted`
> (golden rule 5, ADR-0015 §5).

> **Normative.** The implementation is cut into lanes by the dispatcher under ADR-0137,
> as §10 sets out, and each lane keeps the gate green.

### 2. Which ingests are labelled

> **Normative.** `MemoryIngestor` invokes a reconciler on an ingest exactly when both
> hold: the proposal clears the admissibility floor, and the proposal carries no
> `UserConfirmation`. Neither the proposed memory's band nor any member's band enters the
> condition. On every other ingest none is invoked, no relation is computed, no model
> request is made, and `decide` is called with none.

> **Normative.** The admissibility floor in the clause above is ADR-0159 §2:3's floor and
> tracks it as that clause rules. The condition is a correctness boundary that binds
> `MemoryIngestor` whatever `MemoryPolicy` it holds, as ADR-0159 §2:2's condition did.

> **Normative.** Every other rule ADR-0159 §§2–3, §6 and ADR-0171 §1 make about the
> reconciler binds an asserted ingest unchanged: the certain rung first and
> unconditional, the bound and its rank order, at most one model request per ingest, the
> discard of an unconsulted label, the temporal clause, the never-raises clause, the
> cancellation clause, and the request held inside the ingest lock.

**Why the confirmation exclusion.** A proposal carrying a `UserConfirmation` retires the
assertions the user's yes covered, by ADR-0078 §5b. ADR-0159 §5:1 says a member labelled
`RESTATES` or `ADDS` is "never retired, by any ruling, at any writer". #1326 recorded that
the two have no stated precedence, and ADR-0171 §2 treated the meeting as unreachable
because no crossing holding an assertion was ever reconciled. Labelling every asserted
ingest would make it reachable. Leaving the confirmed proposal unlabelled keeps it
unreachable by the same structure, now resting on the confirmation rather than on the
band. The confirmed proposal is the user's assent to text they were shown, and it is
governed by ADR-0078 §5 already. Its only producer is the interim `RememberCalls`
(`_confirmed` in `orchestration/remembering.py`), which is not wired (Context).

**What holds for a write path a user waits on.** None is wired. If one is wired later,
its ingest pays at most the one bounded request §9 describes, inside the ingest lock,
and an ingest queued behind a reconciling one waits for it, as ADR-0159 §6 already
records for the non-asserted arm. A deployment that finds that wait material may run
with no reconciler and take §6's floor, which retires nothing and asks nothing.

### 3. The asserted arm

> **Normative.** For a proposal in band `ASSERTED` that the admissibility floor and the
> confirmation rule (ADR-0078 §5a) leave to the ordinary rules, `DefaultMemoryPolicy`
> first evaluates ADR-0121 §2's agreeing arm exactly as it stands, and otherwise rules,
> in this order: **(a)** `ASK_USER`, exactly when a member in band `ASSERTED` is labelled
> `CONTRADICTS`; **(b)** otherwise `SUPERSEDE`, naming as `target_id` the best-ranked
> member labelled `CONTRADICTS` whose band is in the retirement class, exactly when one
> exists; **(c)** otherwise `ACCEPT`.

> **Normative.** These arms read relations and bands. They read no retrieval score, no
> rank other than to break a tie among members the relations already selected, and no
> threshold, and `conflicts[0]` is never the target by position.

> **Normative.** On the asserted arm, `DefaultMemoryPolicy` rules `REINFORCE` only by
> ADR-0121 §2. A member labelled `RESTATES` by a model, a member labelled `ADDS`, and an
> unlabelled member are each left current and unchanged, and the proposal is installed
> beside it.

> **Normative.** The `ACCEPT` that (c) produces carries a `reason` telling an empty
> conflict set apart from a non-empty one none of whose members is labelled
> `CONTRADICTS`.

**A restatement the model judged is installed beside, not reinforced.** A `REINFORCE`
adds the proposal's supports to the target and keeps the target's wording (ADR-0328
§11:6). Its standing is the highest origin among the supports that back the claim as
worded. A support from what the user said, added on a model's judgement that two
different wordings say the same thing, would lift the target to "you said it" on that
judgement alone. That is the laundering ADR-0098 §4 forbids. Where the model mislabels a
narrower claim (§8), it would also attach the user's word to content the user did not
state. So the stored
memory stays as it was, and the assertion stands beside it at its own standing. A
verbatim restatement still folds, by ADR-0121 §2, because there the wording is the
user's. A writer exception for a model-labelled fold onto an assertion was the hard half
of #868, and this decision does not open one.

**(a) keeps ADR-0050 §2's purpose.** Two contradictory assertions still cannot both go
live: where any assertion is labelled `CONTRADICTS`, the whole proposal defers, including
the mixed case where a derived member is labelled `CONTRADICTS` too (ADR-0050 §2's
refinement of ADR-0038 §3). What changes is that an assertion which only shares a
subject is no longer treated as one the user contradicted.

**(b) needs no purity condition.** ADR-0159 §4(a) and §4(b) withhold a write where the
stored records disagree with each other, because no ruling on an observation resolves
that. A user's assertion does resolve it. It retires what it contradicts, and leaves what
it restates live beside it.

### 4. A non-asserted proposal beside an assertion

> **Normative.** For a proposal not in band `ASSERTED` whose conflict set holds a member
> in band `ASSERTED`, `DefaultMemoryPolicy` first evaluates ADR-0214 §1's agreeing arm
> exactly as it stands, and otherwise rules `ASK_USER` exactly when a member in band
> `ASSERTED` is labelled `CONTRADICTS`, and `ACCEPT` otherwise.

> **Normative.** That `ACCEPT` carries a `reason` naming it as a proposal beside an
> assertion it does not contradict.

ADR-0038 §3's one-way rule is untouched: an inference never displaces an assertion. An
assertion is in neither target class and in no retirement set (§5), and
`_refuse_unsafe_fold`'s clause 1 still refuses every fold onto one except its two
exceptions (ADR-0214 §3:2). What changes is only when the user is asked. An observer's
inference that shares a subject with something the user said ("Zeno works nights" beside
"Zeno is my roommate") is no longer a question.

**`ACCEPT` rather than ADR-0159 §4's arm.** Running §4(a) and §4(b) here would let an
inference reinforce or supersede a derived member while an assertion sits in the set.
That would be a further change to ADR-0159 §4:1's scope, and no evidence asks for it.
Installing beside destroys nothing, and it is strictly less than the deferral it replaces.

### 5. What a supersession retires

> **Normative.** Whatever relations the writer holds, a `SUPERSEDE` retires the record
> `target_id` names and, beyond it, only those other members of the ruled-on set whose
> band is in the retirement class and which the writer holds a `CONTRADICTS` relation
> for. A member it holds no relation for is left live, whatever its band.

> **Normative.** The clause above withholds from the retirement set only what this
> decision withholds. A member in band `ASSERTED` that ADR-0078 §5b's confirmation covers
> is retired exactly as that section requires, as ADR-0171 §2:2 rules.

> **Normative.** ADR-0159 §5's refusals stand: a member labelled `RESTATES` or `ADDS` is
> never retired, and a `SUPERSEDE` naming one is refused rather than performed.

> **Normative.** The clauses above are enforced at the writer, from the writer's own
> relations, and never read off the ruling. The canonical `MemoryWriter` fake in
> `ai_assistant.testing` carries the same rule, duplicated rather than imported, and the
> shared `MemoryWriter` conformance suite pins it.

> **Normative.** This decision opens no exception to `_refuse_unsafe_fold`'s clause 1 and
> widens neither the reinforce-safe class nor the retirement class. Every write it permits
> was permitted before, and it permits strictly fewer.

This is ADR-0171 §2:1 with its condition dropped. ADR-0171 §2:3 kept the whole sweep where
no contradiction was labelled because that was every asserted correction, and narrowing
there would have left a user's correction unable to retire the stale beliefs it was shown.
Under §2 an asserted correction is labelled, so the stale beliefs it contradicts are
labelled `CONTRADICTS` and retired by name. What the dropped condition swept in besides
was every member the writer had no relation for, which is the loss #3237 measured.

The named target is not re-checked. `DefaultMemoryPolicy` names a target labelled
`CONTRADICTS` (§3(b), ADR-0159 §4(b)) or one a confirmation covers (ADR-0078 §5a). A
foreign policy naming an unlabelled target still retires that one record, and §5:1 stops
it reaching further.

### 6. Where nothing is labelled

> **Normative.** With no reconciler injected, with a request that failed, or for a member
> beyond the bound, every member the reconciler could not label stays unlabelled. Under
> §3 and §4 an unlabelled member is never superseded, never swept into a retirement set,
> and never the ground of an `ASK_USER`. The proposal is installed beside it, or folded by
> ADR-0121 §2 or ADR-0214 §1 where the certain rung admits that.

> **Normative.** That is this decision's ratified behaviour in the degraded case, not a
> fallback outside it. No ingest is refused or ruled differently because a reconciler was
> unavailable, other than by the relations it therefore does not hold (ADR-0159 §6:2).

This is option B of #3237, kept as A's floor. A write never removes a fact on similarity
alone, and a missing label never interrogates the user. The cost is that a real
contradiction the reconciler did not label stays live beside its correction, at a lower
standing than the assertion that corrects it, until a later write or store maintenance
reaches it. ADR-0171 §3 weighed the same trade on the reconciled arm and chose this
direction.

### 7. Which memories a deferral names, and where the observer asks

> **Normative.** `MemoryIngestResult` gains one field, a tuple of record ids defaulting to
> empty. On an `ASK_USER` ruling it holds, in the conflict set's order, the members in
> band `ASSERTED` that the writer holds a `CONTRADICTS` relation for. On every other
> ruling it is empty. Its name is the implementing lane's.

> **Normative.** The writer computes that field from its own relations and never reads it
> off the ruling. The canonical `MemoryWriter` fake fills it by the same rule, and the
> shared conformance suite pins it.

> **Normative.** `MemoryIngestResult.conflicts` keeps the meaning ADR-0078 §4 gave it.

> **Normative.** On an `ASK_USER` ruling the observer raises ADR-0329 §13:1's
> `policy_ask` on each stored memory that field names, and on no other memory. A ruling
> whose field is empty is ADR-0329 §13:3's case: nothing is written and nothing is
> raised.

A question is not a neutral write. It adds the finding's support to the memory as
`against` (ADR-0329 §13:2). Raised on a memory the proposal says nothing about, it is a
false mark on that memory as well as a false question. So the names have to be what the
deferral rests on, and only the writer holds that.

**A new field, not a narrower `conflicts`.** `conflicts` is the bound on what an answer
authorises (ADR-0078 §5): the interim remember path builds its question from it, and a
confirmation's `retires` must lie inside it. Giving it a second meaning on one ruling
would change that bound for a path this decision does not otherwise touch. A separate
field leaves `conflicts` exactly as it is.

An `ASK_USER` from the admissibility floor (secret tier, or unconfirmed outside content)
runs no reconciler (§2), so its field is empty and the observer raises nothing on any
memory. That is the second route #3237's diagnosis found to a question about an unrelated
person, and §13:3 already says what such a finding records.

### 8. A narrower claim

> **Normative.** ADR-0159 §1:1's first two values are read as follows. `RESTATES`: the
> proposed record and the named record make the same claim, so each says everything the
> other says, whatever the wording. `ADDS`: the two records do not make the same claim
> and neither denies what the other says. That covers a proposed record saying more than
> the named one, one saying less, and one saying something different. `CONTRADICTS` is
> unchanged, and no fourth relation is added.

> **Normative.** So a proposed memory that states part of what a stored memory states,
> and nothing that memory does not, stands to it as `ADDS`.

> **Normative.** The reconciler's instruction conveys the two clauses above. Its wording
> is the owner's, in the review of the prompts ADR-0334 makes owner-editable. Until that
> wording lands, the default instruction stands as it is.

**Why `ADDS` and not `RESTATES`, though ADR-0159 §1:1's words admit either.** ADR-0159
§1:1 defines `RESTATES` as "the proposed record says what the named record already says",
which a narrower claim satisfies read literally. But a `RESTATES` label is what lets a
non-asserted proposal fold (ADR-0159 §4(a), as ADR-0161 §1 left it). A fold adds the
proposal's supports to the target as backing its wording as worded (ADR-0328 §11:6), and
that wording is the broader claim. An `ATTESTED` proposal reporting only that Zeno works
nights, folded onto a derived "Zeno works nights and lives at 12 Oak Road", would lift the
whole memory, address included, to "from a source" (ADR-0328 §6) on evidence for half of
it. A fold is honest only where the proposal says everything the target says. So
`RESTATES` is read as the same claim, both ways, and a narrower claim is `ADDS`: installed
beside on every arm, never folded, never retired.

**What this reading changes, and what it does not.** The certain rung is untouched:
ADR-0121 §1's `agrees` holds only between equal wordings, which make the same claim. A
broader proposal was `ADDS` already. The reading narrows `RESTATES` by one case, so
ADR-0159 §4(a) folds on fewer labels and nothing is folded that was not folded before.
A fourth value would change a `core` enum, the prompt and every policy's reading for a
case the three values settle once `RESTATES` means what a fold needs it to mean.

**What waits on the words.** On the asserted arm nothing does: `RESTATES` from a model
and `ADDS` both install beside (§3:3). On the non-asserted arm, today's instruction
calls a more specific belief `adds` and says nothing of a less specific one, so until the
owner's wording lands a model may still label a narrower claim `restates` and fold it, as
it may on `main` now. This decision makes that a mislabel rather than a ruled outcome.
The owner can close it before any lane runs, with an override in the hub's data
directory (ADR-0334 §3:3).

### 9. What it costs

> **Normative.** This decision adds no model request beyond ADR-0159 §3:6's one per
> ingest, and no setting.

The newly labelled populations are an asserted proposal whose conflict set holds a member
the certain rung did not settle, and a non-asserted proposal whose set holds an
assertion. Each such ingest makes at most one request. It covers at most
`reconciler_max_conflicts` members in rank order (default 15, ADR-0171 §1:1), on the
reconciler's own route (`reconciler_model`), under `models/`'s deadline and retry
(`model_timeout_seconds`, default 60, and `model_max_attempts`, default 3). It makes none
where the certain rung labelled every member within the bound, or where the set is empty.
The figures are the settings' defaults on the tree this decision was written against.

The request is the writer's, as on the reconciled arm today. It is not one of the
observer's own calls, so ADR-0329 §16:9's daily bound does not count it, and the number
of such requests is bounded by the number of proposals the observer makes. ADR-0164
§3:1's keys count them with no change, because `reconciled` is stated over ADR-0159 §2's
invocation condition, and §2 here is that condition.

### 10. Delivery

> **Normative.** The implementation is one lane: `core/types.py`, `core/protocols.py`,
> `memory`, `ai_assistant.testing`, the shared `MemoryWriter` conformance suite, the
> observer's question placement in
> `orchestration/observer/writing.py`, and their tests. The new machinery is in `memory`;
> the rest is adaptation (ADR-0137 §1:2).

> **Normative.** The three tests #3237 carries become that lane's regression tests, their
> `xfail` markers removed, and the lane adds each of them run again with a stub
> reconciler supplying the labels the shape calls for.

The lane owes:

- `memory/ingest.py`: `_may_reconcile` under §2; `_retirement_set` under §5:1; and §7's
  field, filled from the writer's own relations.
- `memory/policy.py`: `_rule_on_assertion` under §3, `_rule_on_a_prior_assertion` under
  §4, and the class docstring's rules 6, 8, 9 and 10.
- `core/types.py`: §7's field and its description, and `ConflictRelation`'s docstring for
  §8's reading of `RESTATES` and `ADDS`.
- `core/protocols.py`: `MemoryWriter.ingest`'s paragraph on what a `SUPERSEDE` retires,
  and the field's meaning.
- `testing/writer.py`: the same retirement rule and the same field on the canonical fake.
- `orchestration/observer/writing.py`: `_asked` reads §7's field in place of
  `conflicts`.
- Tests, each failing on a writer or policy that implements only the others:
  - an `ASSERTED` proposal, several `DERIVED` members, no reconciler: nothing is retired,
    and the ruling is `ACCEPT`. This inverts the asserted-path test ADR-0171 §5 asked
    for, which pins the opposite;
  - a foreign policy's `SUPERSEDE` with no relations held: the named target alone is
    retired;
  - an `ASSERTED` proposal, one `DERIVED` member labelled `CONTRADICTS`, one labelled
    `ADDS` and one unlabelled: only the first is retired;
  - an `ASSERTED` proposal and an `ASSERTED` member labelled `ADDS`: `ACCEPT`, no
    question; labelled `CONTRADICTS`: `ASK_USER`, with §7's field naming that member and
    no other member of the set;
  - a narrower `ASSERTED` proposal and a broader `DERIVED` member labelled `RESTATES` by
    the stub: `ACCEPT`, the broader memory current and unchanged, since §3:3 holds
    whatever the label;
  - a narrower `ATTESTED` proposal and a broader `DERIVED` member labelled `ADDS` by the
    stub: `ACCEPT`, the broader memory's supports and standing unchanged;
  - a `DERIVED` proposal and an `ASSERTED` member labelled `ADDS`: `ACCEPT`; labelled
    `CONTRADICTS`: `ASK_USER`;
  - a proposal carrying a `UserConfirmation`: no reconciler invoked, counted against a
    recording reconciler;
  - the observer: a `policy_ask` raised on each memory the field names and on no other,
    and none where the field is empty.

### 11. Relationship to earlier decisions

Superseded in part; every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0038 | §1 and §2, as they reach a conflict no relation labels a contradiction: a user assertion supersedes a derived memory only where the writer labels it `CONTRADICTS`, and false-positive supersession on similarity is no longer the error chosen. §3's ratification of the deferral, as it reaches a conflict set none of whose asserted members is labelled `CONTRADICTS` | §3, §4, §6 |
| ADR-0050 | §1's retirement set, as it reaches a member the writer holds no `CONTRADICTS` relation for on a crossing carrying none. §2's deferral, as it reaches a conflict set none of whose asserted members is labelled `CONTRADICTS` | §5:1, §3:1 |
| ADR-0079 | §3's obligation, on a crossing for which the writer holds no `CONTRADICTS` relation: the target alone is retired | §5:1 |
| ADR-0159 | §1:1's `RESTATES` and `ADDS`, as they reach a proposed record stating part of what the named record states: that is `ADDS`, and `RESTATES` is the same claim both ways; §2:2's first two conditions; §4:4, as it reaches a conflict set none of whose asserted members is labelled `CONTRADICTS`; §5:2's last sentence | §8:1–§8:2, §2:1, §4:1, §5:1 |
| ADR-0171 | §2:3 | §5:1 |
| ADR-0329 | §13:1, in the addition alone: a `policy_ask` is raised on each stored memory the ingest result names as contradicted | §7:4 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0078 §4, §5, §5a, §5b | Nothing: `conflicts` keeps its meaning (§7:3), a confirmed proposal is not labelled (§2:1), and its retirement stands (§5:2) |
| ADR-0092 §4 | Nothing: it fixes which bands an assertion *may* retire, and §5 changes no member of that class |
| ADR-0121 §2, ADR-0214 §1 | Nothing: each arm is evaluated first, exactly as it stands (§3:1, §4:1). Their fall-through clauses say what those ADRs change, and the arms they fall to change at their sources |
| ADR-0159 §1:2–§1:3, §3, §4:1, §5:1, §6 | Nothing: unlabelled, the content-only rule, the reconciler's rules and the non-asserted arm are unchanged; §4:1 folds on fewer labels because §8 narrows `RESTATES` |
| ADR-0164 §3 | Nothing: its keys track the invocation condition by reference (§9) |
| ADR-0328 §11:5–§11:8, §13:4, §16:10 | Nothing: each write a ruling causes is as §11 says; §13:4 keeps the policy reading bands, which every arm here does; a legacy memory still stands at inference |
| ADR-0329 §12:4, §13:2, §13:3 | Nothing: a retiring operation is ruled on as before, a question still rests on an `against` support, and an `ASK_USER` naming no memory still raises nothing |

> **Normative.** This decision records its replacements on the status line and in a dated
> header note of each ADR the first table names, atomically with this ADR under ADR-0070
> and ADR-0082, preserving their ratified bodies. The replacements take effect on this
> ADR's ratification.

## Consequences

**What becomes possible.**
- A write never takes a fact out of current memory on similarity alone. A memory ends
  only where the writer labels it a contradiction, where a confirmation covers it, or by
  the observer's explicit retiring operation (ADR-0329 §12:4).
- The user is asked only about a real conflict with something they said, and the question
  lands on that memory alone.
- A user's correction retires the stale beliefs it contradicts by name, wherever they rank
  within the bound, where before it retired by similarity whatever ranked above the
  threshold.

**What it costs.**
- One bounded model request on each asserted ingest the certain rung does not settle, and
  on each non-asserted ingest beside an assertion (§9).
- The reconciler's `CONTRADICTS` label becomes the one way a write ends a memory or asks
  the user. Its precision on that label is load-bearing.
- Until the owner's wording for §8 lands, a narrower non-asserted claim a model labels
  `restates` still folds onto the broader memory, as it can today (§8).
- Near-duplicates stand side by side. A model-judged restatement of an assertion and a
  narrower claim beside a broader one are both installed beside rather than folded (§3:3).
  Store maintenance (ADR-0329 §2:4) is where they would be tidied.
- A contradiction the reconciler did not label stays live beside its correction (§6), and
  so does a derived member contradicted by an inference whose set also holds an assertion
  (§4).
- A proposal carrying a confirmation no longer sweeps the derived memories near it.

**Migration.** None. The owner said on 2026-10-21 that "nothing in the memory right now is
valuable, so it can happily be erased and restarted". Memories this defect already ended
stay ended, and nothing here restores or re-labels them. The defect matters for learning
from here on, and the deploy that carries the implementing lane may start from an empty
store at the owner's choice. The owner also said privacy and prompt injection should not
constrain designs now, and no clause here leans on either.

**What stays open.**
- Whether a model-labelled restatement of an assertion should fold onto it (#868's hard
  half).
- Whether ADR-0159 §4's arm should reach a set that holds an assertion (§4).
- Whether ADR-0121 §2's agreeing fold should still fire while a derived member is labelled
  `CONTRADICTS`, as it does today.
- The reconciler instruction's wording for §8.

## Alternatives considered

- **B: the asserted arm never retires on similarity, and retirement happens only through
  the observer's retiring operation.** Deterministic and free of model cost. Not chosen as
  the rule, because it stops the loss but not the questions rule 8 raises on similarity,
  and a correction the commit step fails to mark as replacing leaves the stale inference
  live beside it, the outcome ADR-0038 §1 rejected. Kept as this decision's floor (§6).
- **C: memories resting only on legacy supports are not swept.** The smallest change, and
  it covers both observed losses. Not chosen: it still narrows ADR-0079 §3, it leaves the
  observer's own inferences exposed to the same sweep, and it leaves every question. With
  the owner's word that the store may be restarted, a rule for legacy memories buys
  nothing going forward.
- **Fold a model-labelled `RESTATES` onto its target on the asserted arm.** Rejected
  (§3): the fold would lift the target's standing to "you said it" on a model's judgement.
- **A narrower claim as `RESTATES`.** The brief's preference, and what ADR-0159 §1:1's
  words admit read literally. Rejected (§8): on the non-asserted arm it folds, and the
  fold lifts the broader memory's standing on evidence for part of it.
- **A fourth relation for a narrower claim.** Rejected (§8): once `RESTATES` means the
  same claim both ways, `ADDS` already rules it correctly on every arm.
- **Narrow `MemoryIngestResult.conflicts` on an `ASK_USER` instead of adding a field.**
  Rejected (§7): `conflicts` bounds what an answer authorises, and giving it two meanings
  would move that bound for the interim remember path.
- **Label a confirmed proposal too.** Rejected (§2): it would make ADR-0078 §5b's
  confirmed retirement meet ADR-0159 §5:1's "never retired" on one crossing, the precedence
  #1326 left unruled.
- **Leave rule 6 as it stands.** Rejected (§4): an observer's inference is the commonest
  proposal, and it would keep asking the user about every assertion it resembles.
