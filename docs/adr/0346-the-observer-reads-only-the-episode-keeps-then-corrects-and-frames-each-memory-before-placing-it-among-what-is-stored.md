# 346. The observer reads only the episode, keeps then corrects, and frames each memory before placing it among what is stored

- Status: Proposed
- Date: 2026-10-21
- Scope: what the observer reads and when, the scout's findings and what it says about each, the commit step cut into framing, retrieval and placement, the memories the observer keeps and the ones it no longer makes, the track record's source, planning's suggestion of when a memory matters, and the observer's place against outside content. The record these write is ADR-0345's.
- Dependency: ADR-0345, which this decision builds on; ADR-0329, which it changes where §14 names a clause; ADR-0217, ADR-0284, ADR-0307, ADR-0328, ADR-0334 and ADR-0338, as their status lines leave them.
- Authorization: the owner ruled this design in the observer walk of 2026-10-21, in the observer-and-learning fork, and directed it be written ("I think we get started"). This decision writes those rulings down and settles only what they leave open, each such point named where it is settled. The number is provisional until the owner assigns it (`CONTRIBUTING.md` → "ADR numbers are assigned at dispatch"). The owner reads it before it is ratified (§1:1).
- **Contract-surface decision.** It changes `core/types.py` (`EpisodeProjection` carries an earlier exchange's reliance; the observation record's finding carries the scout's annotations; `remember`'s candidate may carry a situation) and adds two prompts to the declared set. It is a breaking change under golden rule 5.
- **Partially supersedes**, in the clauses §14's table names: ADR-0217, ADR-0284 and ADR-0329.

## Context

### What the owner ruled

The walk began with the scout, "what does Scout need in order to find what's
important", and worked outward.

- **The episode is the experience.** "The episode is supposed to represent the
  assistant's experience of processing a specific activation. That means that any
  context, any understanding, any recall should be visible through that experience.
  And so just seeing the episode alone should be enough for Scout." The story, the
  place's history, recall and understanding reach the scout "as a proxy through the
  episode, because that's what the assistant actually experienced, and so that's what
  it has to learn from." As the controller and the phases put more into an episode,
  "that naturally builds on what the observer is allowed to see."
- **The trigger stays.** "It's only needed to go into long-term memory once it falls
  out of short-term memory." How long an episode stays in the window is the episode
  selector's question, not the observer's.
- **Keep, then correct.** Hindsight "comes when that hindsight episode gets processed by
  Scout". Created-then-ended memories are "not a noisier store, it's a more accurate
  store", and the gap between two consecutive episodes' processing is one activation.
- **Inferences belong to store maintenance**, "a better responsibility of that", and a
  single occasion is an ordinary memory with a mark (ADR-0345 §8).
- **What the scout knows, the commit step should not have to rebuild.** Whom a memory is
  about, how they relate to the user, why it matters and who may hear it need "a deep
  understanding of the big user", so they are "given to it earlier on", by the scout.
- **The commit step frames, then places.** Its wording comes from what the finding rests
  on alone; code retrieves what is stored; the model labels each relation; code writes
  (ADR-0345 §4–§5). "Several memories should be committed in order to fully capture what
  the scout flagged as important" is "possible if deemed necessary."
- **Labels ride the hint chain.** Planning, the scout and the commit step may each
  suggest when a memory matters; the commit step decides (owner: "I'm not against the
  commit step writing labels. What about the scout step also writing labels? And … maybe
  planning").
- **Sensitivity is the scout's.** "The commit step doesn't know the user. The whole idea
  is a scout user knows the user." The observer's part is two things: propose a
  narrowing, and carry it onto what it writes.
- **One claim per memory.** "It's just important to try and have memories be as single
  united as possible … if a belief has the word and … it's a clear union of two beliefs
  that should be separated."
- **Framing judges evidence, not importance.** The scout decides what matters; framing
  decides only what the parts bear out (owner: "Yes, I agree").
- **The assistant keeps no belief of its own, for now.** Planning reasons in the moment;
  a memory rests on what the assistant relayed, not on its relay; and where a person
  keeps something the assistant said with nothing behind it, the memory cites what it can,
  the assistant's message: "make it not that there's no source. Instead, it should cite
  what it can." This still prevents the assistant from holding any belief of its own.
  Keeping is not agreeing: "I don't agree, but remember that" keeps the disagreement, with
  the claim word for word, never the claim as the person's.
- **Two things wait.** Preferences on what to keep: "Let's just not think of it now."
  The bar for which single occasions are worth a memory "goes into how to prompt Scout,
  which we won't deal with here today."

### What is there today

Surveyed at `15e62f08`.

- **The scout reads around the episode** (ADR-0329 §8:1): the leaving episode, every
  later episode still in the window, the story's three newest other episodes, and up to
  five past episodes and five memories found by one relevance search. Later episodes are
  shown from every matter and channel. What the episode itself records — understanding's
  reading, the recall it ran, the labels planning was shown — is not shown (§8:6).
- **One scout call per episode**, although §8:3 allows several (`Observer._processed` in
  `orchestration/observer/stage.py`).
- **The commit step sees up to five similar memories and chooses an action**, and the
  write path's reconciler then judges the same relation again (ADR-0345's Context).
- **A single observation is evidence only, never a memory** (ADR-0329 §11:4); an
  inference needs three episodes (§11:5).
- **The track record reads ahead**: a reliance finding rests on the later exchanges'
  parts (§14:2).
- **What an episode records of understanding**: its referents, not the whole windows it
  was shown. The labels planning was shown, both recall runs, the rounds and the digests
  are recorded in full (`EpisodeProcessingRecord`).

## Decision

We will have the scout read only the episode, with what its own record points at, and
propose findings with what it knows of the person: whom each is about, why it matters,
when it matters and who may hear it. Each finding is framed into memories from its parts
alone, the stored memories like each are retrieved by code, each memory's relation to
them is labelled by a model, and the writer writes by ADR-0345. Corrections are handled
when the correcting episode is processed, the track record when the reaction is, and
inferences by store maintenance.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the owner, having
> read it, has authorized its ratification. An assigned number or a green review alone
> does not change its status.

> **Normative.** No lane implements against this decision before it merges `Accepted`, and
> none before ADR-0345's lane has merged (golden rule 5, ADR-0015 §5).

> **Normative.** The implementation is cut into lanes by the dispatcher under ADR-0137, as
> §13 sets out, and each lane keeps the gate green.

### 2. What the observer reads

> **Normative.** For a leaving episode, the observer reads the episode's whole record and
> what that record points at: the memories and episodes its recall runs returned, the
> stories, episodes, notes, memories and results its planning labels name, what its
> understanding's referents name, the question its input answers, and the asking
> activation of an approval its rounds ran under.

> **Normative.** What the record points at is shown to the scout as it stood at the
> episode's time: a memory with the supports, operations and status it had then, from its
> dated supports and operation log (ADR-0328 §4, §5), and a story with the summary version
> it had then. Nothing that happened after the episode is shown.

> **Normative.** The observer reads no episode, story, memory or note that the leaving
> episode's record does not point at, and runs no search to find one. ADR-0329 §8:1's
> later episodes, story reads and relevance searches are not read.

> **Normative.** The leaving episode's understanding, its latest version, is rendered to
> the scout: its meaning and ground, its references with what each resolved to, its
> relationships, what it left unresolved, and the answers it recorded.

> **Normative.** ADR-0329 §8:4 and §8:5 stand: no held result, no hidden thinking and no
> diagnostic record is read, and every span reaches a model as quoted source data,
> attributed from the record.

> **Normative.** The scout is given the leaving episode's person's profile fields, as
> ADR-0338 §9:1 has it.

**The past for reading, the present for writing.** The scout learns from the experience
as it was lived, so it sees what the assistant knew then. A memory recalled as current
and ended since is shown current, because that is what the assistant saw; anything
learned later reaches the store through its own episode. Retrieval and placement (§6)
read the store as it stands now, so what is written is filed against what is true today.

**What the record does not yet hold.** The windows understanding was shown are recorded
only as far as its referents cite them. The owner's ruling is that the episode grows to
hold the experience; when it records more, the observer reads more under §2:1, and no
decision here needs to change.

### 3. Keep, then correct

> **Normative.** The observer commits only findings that rest on the leaving episode's own
> parts, and shows the scout nothing that occurred after the leaving episode.

> **Normative.** A correction, a retraction or a joke revealed in a later activation is a
> finding of that activation's episode when it is due, and its write changes the earlier
> memory by ADR-0345 §3 and §5.

Consecutive episodes are processed one activation apart, and in the same run where both
are due, so a memory a later episode corrects is uncorrected for about one activation.
While it is, the correcting episode is still in the window, where understanding sees it.

### 4. The scout

> **Normative.** The scout is one model call per due episode, over what §2 reads. ADR-0329
> §8:3's several-episodes call is not made.

> **Normative.** Each finding states one thing worth keeping, which may hold several claims
> that share its annotations, and names the parts of the leaving episode it rests on, as
> ADR-0329 §9:1 has it. It also gives: the people it is about and the people it involves
> (ADR-0345 §9:1), each named as the record names them, the owner included where it is
> about them; why it matters to the person, in words; any situations in which it matters,
> in words; and, where it should reach fewer people than its default, a proposed narrowing
> with a note on why.

> **Normative.** Where parts the scout would propose together call for different
> annotations, different people, a different reason it matters, different situations or a
> different narrowing, it proposes them as separate findings.

**The scout splits by handling, framing by claim.** Every memory framed from a finding
takes that finding's annotations, so what must be treated differently, "Ana is my
sister" beside "Ana is pregnant, don't tell anyone", has to part at the scout. Turning a
finding into single claims, "Ana lives in Lisbon" and "Ana teaches piano", is framing's,
which sees the parts exactly (§5:3).

> **Normative.** The scout's annotations are hints. None sets an origin, a holder or a
> standing, and none is evidence.

> **Normative.** The observation record keeps each finding's annotations beside its claim
> (ADR-0329 §16:1), so a retry commits what the scout proposed.

### 5. Framing

> **Normative.** Each finding is framed by one model call, given only: the claim; the parts
> it rests on, each with the message it answers where it is a reply; the scout's
> annotations; and the person's profile fields. No stored memory is shown to it.

> **Normative.** The framing call proposes one or more memories, each with: its wording;
> its supports and, for each, the fields ADR-0329 §9:4 names; its `subjects` and
> `involved`, each a set, possibly empty, never left unset; its
> situation labels; its marks; a validity end where its supports name one (ADR-0345 §6);
> and, under the person model, the style and pin judgements ADR-0338 §9:4 and §9:5 name.

> **Normative.** Each memory a framing proposes states one claim. Claims that could each be
> true without the other are framed as separate memories, as "Ana lives in Lisbon" and "Ana
> teaches piano" are; a claim that holds only as a whole, as a relation ("Ana and Tom are
> married"), a range or a name does, stays one.

> **Normative.** Every memory a framing proposes rests only on the finding's parts, and
> code checks each as ADR-0329 §9:5 checks a decision. A memory that fails a check is not
> written, and the others stand.

> **Normative.** The framing call may keep, change, add or drop each person the scout named,
> and keeps a name only where a part the memory rests on gives that name, as ADR-0345 §9:3
> has it.

> **Normative.** A relationship between the user and another person is framed as a memory
> of its own with that person as a subject, such as "Ana is the user's younger sister", and
> other memories about that person use the same name for them.

> **Normative.** A framing call may also decide that nothing in the finding is worth
> keeping, with a reason, where the parts do not bear the claim out.

> **Normative.** Every memory a framing proposes carries the finding's proposed narrowing,
> as a proposal at its create within ADR-0217 §4's bounds.

**Why framing judges evidence and not importance.** The scout decided the finding is
worth keeping. Framing decides only what the parts bear out: a habit read from an
approval, a detail no part states, a claim about the user resting on the assistant's
words alone (ADR-0329 §10) are refused there. Importance is not judged twice.

### 6. Retrieval and placement

> **Normative.** For each memory a framing proposes, code retrieves the stored memories, as
> they stand when it retrieves them, similar enough to it: by relevance to its wording
> above a composition-root threshold,
> and every memory naming a person it names, in either field (ADR-0345 §9:6), up to a
> composition-root bound.

> **Normative.** Each memory is placed by one model call, given the memory as framed and
> each retrieved memory in a compact form code builds from the stored record: its wording,
> holders and partial supporters, standing, status, the counts of its counted `for` and
> `against` supports and the distinct episodes they point at, its open questions, and its
> most recent supports in full, up to a composition-root number. It names one ADR-0345 §4
> relation for each retrieved memory, with the note ADR-0345 §4:1 asks for, and at most
> one open question the new memory answers.

> **Normative.** The compact form is computed, never written by a model, and the placement
> call makes no further read. Where it cannot place a pair from what it is shown, it says
> `unclear`, and its note says what it would have needed.

> **Normative.** The placement call does not change the framed memory. It states relations
> only.

> **Normative.** Every `unclear` the placement call names is recorded on the finding's
> outcome in the observation record (ADR-0329 §16:1), with its note and the memory it
> named, and in the diagnostic record where that record is on, so where the set of
> relations does not fit can be seen.

> **Normative.** The memory is proposed to `MemoryWriter.ingest` through the write stage as
> a placed proposal (ADR-0345 §4), with the revision each retrieved memory was read at.

> **Normative.** A placed proposal the writer refuses as stale (ADR-0345 §4:7) is retrieved
> and placed again within the same attempt, up to a composition-root count, and is
> otherwise the attempt's failure under ADR-0329 §16:4.

> **Normative.** On an `ASK_USER` from the policy's admissibility floor, the observer
> raises nothing and the finding's outcome records the ask (ADR-0336 §7:4).

### 7. What the observer keeps, and what it no longer makes

> **Normative.** A single occasion that the scout proposes and framing bears out is kept as
> a memory marked `one_occasion` (ADR-0345 §8). ADR-0329 §11:4 no longer holds.

> **Normative.** The observer creates no memory whose standing would be inference alone,
> and adds no support pointing at an observer's inference. Drawing inferences across
> memories is store maintenance's, under its own decision.

> **Normative.** ADR-0329 §11:1–§11:3, §11:7 and §11:8 stand: an explicit request or a
> correction is always kept, a passing fact and a report are kept where worth keeping, a
> confirmed memory needs no bar, and a sensitive topic is kept under the same rules.

> **Normative.** The observer reads every origin and holder from the record as code sets
> them, and computes neither from a model's output or from the task-level outside mark.

> **Normative.** Where a round's message relays what a recorded part of the episode says, a
> finding rests on that part and not on the message: the dentist's email the assistant
> read, not the assistant's sentence repeating it.

> **Normative.** Until a decision on the assistant's standards of belief decides otherwise,
> no memory rests on a round's message unless a person, in the leaving episode, asked to
> keep what it said, agreed with it, or confirmed it. The ADR-0329 §10 rule that the
> assistant's words are never evidence about the user extends to every memory, about
> anything.

> **Normative.** A memory a person keeps or adopts from a round's message rests on the
> person's request, agreement or confirmation, which backs it as worded, so it is held by
> that person. It carries the message as a support, so it cites where and when the
> assistant said it, and framing marks it `assistant_statement` where no recorded part
> behind the message was found (ADR-0345 §8).

> **Normative.** Where the person asks to keep what the assistant said but says they
> disagree with it, the observer keeps one memory, marked `one_occasion`, worded as the
> person's disagreement with the assistant's claim, carrying that claim word for word and
> when the assistant made it, resting on the person's reply read with the message it
> answers and on that message, and held by the person. It never keeps the claim the person
> disagreed with as the person's belief.

**No beliefs of the assistant's own, for now.** Planning reasons in the moment, and a
matter's working conclusions live on its story's page. Long-term memory holds what
people and sources believe. Where the assistant's words end up in a memory, it is because
a person took them on, and the memory cites the assistant's message, where and when it
was said, and marks that nothing else stood behind it. Whatever else was in that round's
context stays one pointer away, in the episode the support points at.

### 8. The track record

> **Normative.** `EpisodeProjection` gains, for an episode whose rounds called the
> reliance capability (ADR-0329 §6:7), the memories each call named and what it said each
> shaped.

> **Normative.** A reliance is recorded in the track record when the episode in which the
> user reacted to what it shaped is due: the scout proposes a reliance finding for each
> earlier exchange's reliance that episode shows, resting on the leaving episode's parts.

> **Normative.** A reliance finding is not framed, retrieved or placed as a new memory. One
> call on the placement step's prompt, given the reliance, the memory it named and the
> parts the finding rests on, decides held up, let down or neither, as ADR-0329 §14:2
> decides it from those parts.

> **Normative.** A reliance whose outcome the leaving episode itself shows, an action it
> ran, is recorded when that episode is due.

> **Normative.** ADR-0329 §14:3 and §14:4 stand.

### 9. Where a memory matters

> **Normative.** `remember` takes one further optional argument, the situations in which
> the fact matters, in words. Its candidate carries it, and the scout is shown it as part
> of the candidate.

> **Normative.** Where a reliance is recorded as held up, the call that recorded it may add
> what the reliance shaped to the memory's labels, through ADR-0345 §7:6.

> **Normative.** Framing decides each new memory's labels. Planning's and the scout's are
> suggestions it may keep, change or drop.

> **Normative.** Where a `restates` folds a finding into a stored memory that neither of the
> leaving episode's recall runs returned and no planning label named, the observer adds the
> finding's situations (§4:2) to that memory's labels, through ADR-0345 §7:6, each citing
> the leaving episode. Code decides the miss from the episode's record.

**Labels learn from successes and from misses.** A reliance that held up adds the
situation it helped in. A person having to say again something already kept, in a
situation where the memory did not come up, shows recall missed it there, so that
situation becomes a label: "I'm allergic to peanuts", said again while booking a
restaurant, teaches the allergy to surface when booking restaurants.

### 10. Prompts and models

> **Normative.** The framing call and the placement call each render a prompt of their own,
> declared under ADR-0334 with the scout's. `observer_commit` is retired, and its
> override, where a hub holds one, is not loaded.

> **Normative.** The framing and placement calls ride the commit step's model route
> (ADR-0329 §9:9), and the daily bound counts every call the observer makes (ADR-0329
> §16:9).

> **Normative.** The prompts' wording is the owner's, through ADR-0334's review. The
> decision fixes what each call is given and what its reply carries, and no prompt
> wording.

### 11. What stays open

> **Normative.** This decision decides no preference of the person about what is kept, no
> bar for which single occasions are worth a memory beyond ADR-0329 §11, no search over
> labels, no rule of usage among holders, and no standard by which the assistant comes to
> hold a belief of its own. Each is a later decision's, and no lane builds one under this
> decision.

### 12. What the person sees

> **Normative.** ADR-0329 §18 stands: the belief panel shows pending candidates, to the
> owner alone, and nothing else is added to what the person sees here.

### 13. Delivery

| Lane | What it lands | Where |
| --- | --- | --- |
| 1 | The projection's reliance (§8:1) and `remember`'s situations (§9:1) | `core`, `orchestration` |
| 2 | The observer: §2's reading, the scout's annotations, framing, retrieval and placement, the two prompts, and the writes as placed proposals | `orchestration/observer`, `app`, `core` |

> **Normative.** Lane 1 merges after ADR-0345's lane, and lane 2 after lane 1.

> **Normative.** Lane 2 goes live in one deploy, with the owner's prompt drafts for the two
> new prompts placed by the owner's direction (ADR-0334 §6). Episodes already processed are
> not processed again.

### 14. Relationship to earlier decisions

Superseded in part; every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0217 | §4:2, in the addition alone: the observer of ADR-0329 also proposes, on its framing pass | §5:8 |
| ADR-0284 | §8:1's projection, in the addition alone: an episode's reliance | §8:1 |
| ADR-0329 | §8:1, §8:2, §8:3 and §8:6; §9:3 and §9:4; §9:7, for the observer's own writes; §10:1 and §10:2, in their reach, which extends to every memory; §11:4, §11:5 and §11:6; §12:4; §14:1 and §14:2; §9:1, in the additions and in its one claim per finding; and §3:1, in the additions alone | §2–§10 |

## Consequences

**What gets easier.**
- The scout learns from what the assistant actually experienced, with no reads of its
  own and no unrelated matters mixed in.
- A correction is a write on the corrected memory, recorded when it happens, and the
  history stays readable.
- The commit step's two questions, what is true and where it goes, are asked separately,
  each with only what it needs.
- The observer is ready for the outside-content rework: it reads provenance and computes
  none, and its framing call is a narrow call given only a finding's parts.

**What gets harder, and what this leaves.**
- **More calls per finding:** a framing call, and a placement call per memory. The
  reconciler's call goes, and the daily bound still caps the total.
- **The assistant remembers nothing of its own.** What it concluded in one activation is
  re-concluded in the next, from what it is shown. Earned opinions wait for a decision on
  its standards of belief.
- **No inferences until store maintenance exists.** #3154's scenario "an inference and its
  bar" moves to that decision's milestone.
- **What the scout knows is what the episode recorded.** Understanding's windows are not
  yet recorded whole.
- **The owner's `observer_commit` override retires.** The two new prompts need drafts,
  which is the prompts front's.
- **#3154's scenarios change:** a correction now lands one activation later, the track
  record comes from the reaction, and a single occasion becomes a memory. The acceptance
  is reworked for this decision.

## Alternatives considered

- **Reading the story, the place's history and recall separately.** The walk built this
  first: the story around the exchange, the place's neighbours, and a two-way recall.
  Withdrawn for the episode alone, since each reaches the scout through what the episode
  recorded.
- **Hindsight read ahead.** ADR-0329's design. Withdrawn: it showed unrelated later
  exchanges by count across every channel, and the correcting episode is processed one
  activation later anyway.
- **Inferences in the observer, from one episode's recall.** Not chosen: whether the
  occasions came together would depend on what each activation happened to recall.
- **Importance judged twice.** Not chosen: the scout judges importance, and framing judges
  only what the parts bear out.
- **The commit step proposing sensitivity.** Withdrawn by the owner: it does not know the
  person.
- **Keeping the assistant's own conclusions as its memories,** resting on the evidence
  they drew on. Not chosen for now: an advertisement read in one activation would become
  a lasting opinion the assistant keeps raising. It waits for a decision on the
  assistant's standards of belief.
