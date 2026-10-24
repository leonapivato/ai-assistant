# 347. A story keeps every summary it has had, and the observer reads the one an activation started with

- Status: Accepted
- Date: 2026-10-23
- Scope: what the story store keeps of a summary a later version replaces, the read that returns it, what forgetting does to it, the story store's position an episode records when its activation starts, which version the observer shows the scout for a story an episode points at, and the upgrade. Issue [#3387](https://github.com/leonapivato/ai-assistant/issues/3387), a separate decision after ADR-0346, as the owner directed.
- Dependency: ADR-0275, ADR-0286, ADR-0289, ADR-0300, ADR-0303, ADR-0304, ADR-0326, ADR-0332 and ADR-0346, as their status lines leave them.
- Authorization: on 2026-10-23 the owner asked "why not just save old summaries?" and directed "separate decision after B". This decision writes that down and settles only what it leaves open, each such point named where it is settled. The number is provisional until the owner assigns it (`CONTRIBUTING.md` → "ADR numbers are assigned at dispatch").
- **Contract-surface decision.** It changes `core/protocols.py` (`StoryStore` gains a read of the summary a named version wrote, and a read of its position) and `core/types.py` (`EpisodeProcessingRecord` gains the story store's position, defaulted so a record written before it validates unchanged). It is a breaking change under golden rule 5.
- **Partially supersedes**, in the clauses §7's table names: ADR-0286, ADR-0300 and ADR-0346.

## Context

**What the observer needs.** ADR-0346 §2:2 shows the scout what an episode's record points at as it stood at the episode's time, a story "with the summary version it had then", so the observer learns without hindsight. Its §2:3 then falls back to the story's identity alone, "since a replaced summary's text is not kept (ADR-0300 §3:6)". A tidy-up that runs before the episode leaves the window replaces the summary, so the scout often learns without the story context planning had, which is the context that explains a round.

**What there is today.**
- **Only the current summary is kept as text.** ADR-0300 §3:6: "Only the current page is kept as text: writing a new one discards the old one's text." ADR-0304 §2:1–§2:2 renames the page the summary and keeps that rule. The SQLite store keeps one row per story, overwrites it on each write, and runs with `secure_delete` on, so the old text leaves the file. A test pins that.
- **The version log holds identities, instants and enumerations only** (ADR-0303 §4:3). Each version has an id from one store-wide counter, its `written_at`, and the notes and episodes it took in. It holds no free text.
- **No record names the version a model call was shown.** Understanding's story referent carries the story's id and the first line of its summary as an excerpt. A planning label carries the id alone. A round carries no story version. Planning re-reads its stories before every round, so one activation can be shown more than one version of a story, and its own tidy-up runs beside its rounds (ADR-0307 §7).
- **The store orders its writes; the clock does not.** A summary write carries the `as_of` of the read it was built on and is refused "where a version has been written since", so a version's number and a read's `as_of` lie on one increasing sequence the store issues. An episode's `started_at` is an injected wall-clock reading that may run backwards and is no proof of causal order (ADR-0275 §4:9).
- **Forgetting reaches no story.** ADR-0304 §5:1: "Until the learning design decides forgetting for stories, forgetting a conversation reaches no story's notes, summary or version log", and "a summary may keep text from a forgotten conversation". ADR-0304's *What stays open* lists what forgetting must later reach, among them a story's "summaries, current and earlier".

**Why ADR-0300 refused old versions.** Its Alternatives: "A forgotten episode's content would survive in them." That was written while forgetting was still to reach the page. ADR-0304 §5:1 has since let the current summary keep a forgotten conversation's text too, so the reason no longer separates old versions from the current one. Both wait on the forgetting design.

## Decision

We will have the story store keep every summary it writes, read by its version; have each episode record the story store's position when its activation starts; and have the observer show the scout each story an episode points at in its latest version at or below that position.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the owner has
> authorized its ratification.

> **Normative.** No lane implements against this decision before it merges `Accepted`
> (golden rule 5, ADR-0015 §5).

### 2. Every summary is kept

> **Normative.** Every summary a write makes is kept after a later write replaces it, with
> the version that wrote it, its `written_at`, its lines and its mark, exactly as written.
> ADR-0300 §3:6's "writing a new one discards the old one's text" no longer holds.

> **Normative.** The kept summaries live beside the version log, not in it: the log stays as
> ADR-0303 §4:3 has it, identities, instants and enumerations only.

> **Normative.** A kept summary never changes, and nothing removes one, as nothing removes a
> note or a version (ADR-0303 §2:3).

> **Normative.** `StoryStore` gains `summary_at(story_id, version)`, which returns the
> summary that version of that story wrote, as a `StorySummary`, and `None` where the
> store holds no text for it or the version is not that story's. It is `async`, as every
> member of the store is.

> **Normative.** `StoryStore` gains `position()`, which returns the store's latest position
> on the sequence its versions and reads' `as_of` lie on: every version written before the
> call has a number at or below it, and every version written after has a number above
> it. It is `async`.

**Why beside the log and not in it.** The log is what flags, the matters pass and the
owner's views read by identity, and ADR-0303 kept it free of text so that a version's
record never carries what a note said. The text is read by one caller, by version, and a
table of its own keeps the two apart.

### 3. Forgetting

> **Normative.** ADR-0304 §5:1 stands: forgetting reaches no story's summary, the current
> one or a kept one. The decision on forgetting for stories that ADR-0304's *What stays
> open* names reaches the kept summaries with the rest.

A kept summary can hold a forgotten conversation's text for longer than the current one,
since a later tidy-up may drop it from the current summary while the kept one keeps it.
That widens what the forgetting decision must reach, and changes nothing a person can see
today. No version is erased by rule now, and a rule erasing only the versions that took a
forgotten episode in would not be enough: the log names an episode once, at the version
that first took it in, and every later version carries its content forward.

### 4. What the observer shows for a story

> **Normative.** When an activation is admitted, the writer reads the story store's
> `position()` and records it on the episode's processing record as `stories_position`,
> beside `started_at` (ADR-0286 §2:1). It defaults to `None`, so a record written before
> it validates unchanged and `schema_version` does not move, as ADR-0332 added `joined`.

> **Normative.** For a story the leaving episode's record points at (ADR-0346 §2:1), the
> scout is shown the summary of that story's latest version whose number is at or below
> the episode's `stories_position`, read through `summary_at`. No clock reading chooses
> the version.

> **Normative.** Where the episode records no `stories_position`, no version of that story
> lies at or below it, or the store holds no text for that version, the story is shown by
> its identity alone, marked as no longer held, as ADR-0346 §2:3 has it.

**Why the position an activation started at.** No record names the version a call was
shown, and planning re-reads its stories each round, so "the version it had then" is
not one version. The version at the start is the one every read of the activation
began from, and the store's position, unlike `started_at`, cannot run backwards, so a
version written after the episode is never chosen whatever the clock did. A version
written during the activation is most often its own tidy-up's, made from the notes the
activation wrote, which the episode records and the scout reads. Another activation's
tidy-up landing mid-activation is missed: the scout then knows less than planning did,
never more, which is the direction ADR-0346 §2 keeps.

### 5. The upgrade

> **Normative.** On open, the story store upgrades in place, with nothing dropped (ADR-0326
> §4:1): each story's current summary is kept as the text of the version that wrote it,
> and no earlier version gains text.

> **Normative.** The story store's label advances, a file at the previous label is upgraded
> rather than refused, and the lane ships ADR-0326 §4:2's test over a file the previous
> release wrote and raises the story store's `Store.shape` in `scripts/upgrade_stores.py`
> with a carry from the shape it replaces (ADR-0326 §7).

### 6. Delivery

> **Normative.** The implementation is one contract-surface lane under ADR-0137 §2:
> `StoryStore.summary_at` and `position`, their conformance cases, the canonical
> `FakeStoryStore`, the SQLite story store keeping every summary, the upgrade, and the
> admission write recording `stories_position`. The test that pins a replaced
> summary's text leaving the file is replaced by one that pins it kept.

> **Normative.** The observer's read of §4 lands in ADR-0346's lane where this decision's
> lane has merged before that lane is briefed, and otherwise as a follow-on lane in
> `orchestration/observer` once both have merged.

> **Normative.** Each lane holds `core/protocols.py` alone while it runs, so this decision's
> lane is sequenced against ADR-0345's and ADR-0346's lanes and never runs beside them.

### 7. Relationship to earlier decisions

Superseded in part; every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0286 | §2:1, in the addition alone: the admission write also records the story store's position as `stories_position` | §4:1 |
| ADR-0300 | §3:6, in its last sentence alone: a replaced summary's text is kept, beside the version log | §2 |
| ADR-0346 | §2:2, for a story, in the addition alone: the version shown is the latest at or below the position the activation recorded at its start; §2:3, for a story, in its reason: a story falls back to its identity where no position or no text is held | §4 |

## Consequences

**What gets easier.**
- The scout learns with the story context planning started from, for every episode the
  decision's lane reaches.
- The owner's views and a later history read have every summary to show, by version.

**What gets harder, and what this leaves.**
- **More is kept.** Every tidy-up keeps a few short lines. A story's kept summaries grow
  with its tidy-ups, bounded by nothing but forgetting.
- **Forgetting has more to reach.** The forgetting decision for stories now covers the
  kept summaries, which can outlast the current one.
- **Episodes from before the lane** record no `stories_position`, so the scout shows their
  stories by identity alone.
- **One more read at admission,** of the story store's position, for every activation.
- **The start version is not every version planning saw.** A version another activation
  wrote mid-activation is not shown. If the record shows that matters, a later decision
  can have the episode name each version it was shown.

## Alternatives considered

- **Choosing the version by `written_at` against `started_at`.** Drafted first and
  withdrawn in review: both are wall-clock readings, which may run backwards (ADR-0275
  §4:9), so a summary written after the episode could be stamped before its start and
  show the scout what happened later.
- **Recording on each call the version it was shown,** on the story referent, the planning
  label or the round. Not chosen now: it is exact, but it reaches understanding, planning
  and the episode record for every story read, where the start version misses only another
  activation's tidy-up landing mid-activation.
- **The episode copying the summary it was shown.** Not chosen: one copy per episode
  rather than one per version, each of which forgetting would later have to reach.
- **Each version's text in the version log.** Not chosen: the log stays free of text
  (ADR-0303 §4:3), and only the observer reads the text, by version.
- **Erasing the versions that took in a forgotten episode.** Proposed in the walk and
  withdrawn: forgetting reaches no story today (ADR-0304 §5:1), and the log names an
  episode only at the first version that took it in, so later versions would keep it.
- **Keeping only the current summary,** as ADR-0300 §3:6 has it. Withdrawn by the owner:
  "why not just save old summaries?"
