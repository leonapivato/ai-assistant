# 348. Keeping a claim is not believing it, a holder's newer word supersedes their older one, and a memory holds one open check

- Status: Proposed
- Date: 2026-10-25
- Scope: three corrections to how a memory's holders, disputes and open questions are written, found by milestone 3's acceptance run (#3397). What a person's request to keep something backs. A holder's older word cited against their newer memory. A memory's open `recheck` questions, and how an answer closes one. Issues [#3400](https://github.com/leonapivato/ai-assistant/issues/3400), [#3403](https://github.com/leonapivato/ai-assistant/issues/3403) and [#3413](https://github.com/leonapivato/ai-assistant/issues/3413).
- Dependency: ADR-0328, ADR-0345 and ADR-0346, as their status lines leave them.
- Authorization: the owner ruled each rule on 2026-10-25, reviewing milestone 3's exit. Their words are under each rule in the Context. The number is provisional until the owner assigns it (`CONTRIBUTING.md` → "ADR numbers are assigned at dispatch").
- **Contract-surface decision.** It changes what `MemoryWriter.ingest` writes for a placed proposal, which the shared writer suite pins (ADR-0345 §15). No type or Protocol member changes. It is a breaking change under golden rule 5.
- **Partially supersedes**, in the clauses §5's table names: ADR-0345 and ADR-0346.

## Context

Milestone 3's acceptance run, and its re-run after the fixes, drove the observer of ADR-0346 and the record of ADR-0345 end to end on a scratch hub. Three results came from rules as written, not from defects in the code.

**1. "Remember that" made the person a believer.** The owner asked for a forecast, the assistant reported it, and the owner said "remember that". ADR-0346 §7:7 and §7:10 count a person's request to keep something as backing it as worded. ADR-0345's worked example, step 3, has the owner hold the page's claim after "remember that", and ADR-0345 §8's prose says the request "takes on the words shown". The owner, verbatim:

> "If I say remember that, that doesn't mean I believe that. Which means that if I say remember that, it shouldn't be implied that I'm backing that, right?"

Treating a request to keep as belief would let anything a person asks the assistant to remember, an advertisement or a rumour, count later as that person's own belief. ADR-0345 was built to refuse that loop.

**2. A correction read as the person disputing their own new fact.** After "My dentist is Monday" and then "No, it's Tuesday":
- the write was right: the person's Monday backing was withdrawn and the Monday memory retired (ADR-0345 §3);
- but framing cited the earlier Monday statement on the new Tuesday memory as `against`;
- nothing stops a support framing chose, so planning's label read the current memory as "disputed by the user".

ADR-0345 §3:7 already ends a holder's own older dispute when a restatement folds. It does not reach a newly installed memory. The owner: "I thought that you couldn't dispute your own claim. Doesn't that just get rid of the backing?" Then: "it seems like a pretty straightforward fix".

**3. A duplicate question could not be closed.**
- A memory already holding an open `recheck` question received a second one for the same concern. The placement call's own note said "this relation is not needed".
- The person's answer closed the first question.
- It could not close the second, because ADR-0345 §5:9 resolves a question only where the relation adds the answering support, and the support was already on the memory.

The owner agreed both changes below: "Okay, yeah, looks good."

## Decision

We will treat a request to keep a claim as citing it, never backing it; let a holder's newer word supersede their own older contrary word wherever it lands; and keep one open `recheck` question per memory, closed by an answer whose support the memory carries.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the owner has
> authorized its ratification.

> **Normative.** No lane implements against this decision before it merges `Accepted`
> (golden rule 5, ADR-0015 §5).

### 2. Keeping a claim is not believing it

> **Normative.** A person's part backs a memory as worded only where it states the claim
> itself, agrees with it or confirms it. A part that only asks to keep a claim stated
> elsewhere, as "remember that" or "keep that" does, is cited `for` the memory and backs
> nothing as worded.

> **Normative.** A memory kept at a person's request from what a source reported is held by
> that source, by ADR-0345 §2's table, and cites the request. The person becomes its holder
> only by stating, agreeing with or confirming the claim, in that episode or later.

> **Normative.** What a person asks to keep from a round's message alone is kept as a record
> of the saying (ADR-0345 §2:4), "On Oct 20 the assistant said …", marked `assistant_statement`
> and `occasion`, held by the assistant's statement and citing the request. It is kept as the
> person's claim only where the person agreed with what the message said, rather than only
> acknowledging it, or confirmed it (ADR-0346 §7:7).

> **Normative.** A person who states a claim themselves holds it whatever words surround it.
> "Remember I'm allergic to peanuts" states the allergy, and a yes to a wording the assistant
> rendered confirms it (ADR-0329 §5:5). Neither changes here.

**Why the request still matters.** It is cited, so the record keeps who asked for the memory
and when. It is also what ADR-0346 §7:3 keeps unless the person said not to. It decides that
something is kept, not whose belief it is.

### 3. A holder's newer word supersedes their own older one

> **Normative.** Where a placed write installs a memory, each counted `against` support on it
> whose holder is a holder of one of its backing supports, and whose part comes before that
> holder's backing part in the record's order, stops counting in the same write, citing that
> holder's backing support. ADR-0345 §3:7 does the same where a `restates` folds.

> **Normative.** The record's order is the only order this clause reads. An earlier episode
> comes before a later one, and within one episode an earlier part comes before a later one.
> No clock reading decides it (ADR-0275 §4:9).

> **Normative.** A holder's part that comes after their backing part keeps counting, whatever
> its direction. Newer evidence from a person against their own memory, as "I had chicken
> yesterday" against "the user is vegetarian", is evidence and stays counted.

**Why stopped and not dropped.** A stopped support stays on the memory (ADR-0328 §5:8), so
the history still shows what the person said before, and that it no longer counts.

### 4. One open check per memory, closed by its answer

> **Normative.** A `recheck` relation raises no question on a stored memory that already holds
> an open `recheck` question, and writes nothing to that memory. The write reports the relation
> and its note, and the producer records them on its outcome, as it records an `unclear`
> (ADR-0346 §6:5).

> **Normative.** A question the placement names as answered is resolved citing a backing
> support of the proposal that the memory carries once the write is applied, whether this write
> added it or the memory already carried it. It stays open where the memory carries none.

**Why one.** A `recheck` question rests on the memory's own backing (ADR-0345 §5:9), so two open on one memory rest on the same thing and ask the same question: is this still so? "Worth checking" is a state of the memory, not a list of concerns. The reason a later relation gives is kept on the outcome, where the viewer shows it.

### 5. Relationship to earlier decisions

Superseded in part. Every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0345 | §3, in the addition alone: a holder's older `against` stops counting on an installed memory; §5's `recheck` row and §5:9, as to a memory already holding an open `recheck` question and as to an answer whose support the memory already carries; §8:1, in "kept or took on", which now reads "took on by agreeing or confirming"; §15:2's worked example, in step 3's holders, where M5 is held by the page alone and the owner's request is cited | §2–§4 |
| ADR-0346 | §7:7, in "asked to keep it": a request alone keeps a record of the saying, never the claim; §7:10, in "request … which backs it as worded": a request backs nothing, while agreement or confirmation backs it | §2 |

## Consequences

**What gets easier.**
- "Remember that" can no longer turn a source's claim, a rumour or an advertisement into the person's own belief.
- A correction leaves the current memory undisputed.
- A memory the person has just confirmed is not left with a question nobody can close.

**What gets harder, and what this leaves.**
- **Framing must tell keeping from stating,** which is a judgement. The prompt carries it, and the prompt suite measures it. Code cannot tell a request to keep from a statement, so it does not try.
- **The worked example's step 3 ends the same** at its table, since M5 is held by the page there already. Only its narration changes.

**Delivery.** One lane under ADR-0137 §2:
- the writer's §3 and §4 rules in `memory`, with their writer-suite cases and the fake;
- the observer recording §4's reported relation on its outcome;
- the framing prompt for §2, with prompt-suite cases for "remember that" after a source report and after the assistant's own message.

Afterwards #3154's scenario 9 is re-run with its expectation as §2 has it: held by the source, citing the request.

## Alternatives considered

- **Counting "remember that" as belief, as ADR-0345 and ADR-0346 had it.** Withdrawn by the owner: keeping is not believing.
- **Telling framing not to cite a corrected statement against its correction.** Not chosen alone: corrections are the most common thing learned, and a code rule holds on every write where a prompt holds only as often as the model follows it. The prompt may still say it.
- **Hiding a holder's own `against` support from planning's label alone.** Not chosen: the evidence summary would still count it, and the label would then disagree with the record.
- **Letting several `recheck` questions stand and closing them all on one answer.** Not chosen: several open questions resting on the same supports say nothing one does not.
