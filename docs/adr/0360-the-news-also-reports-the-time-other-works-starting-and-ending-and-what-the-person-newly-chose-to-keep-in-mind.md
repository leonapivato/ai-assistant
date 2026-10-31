# 360. The news also reports the time, other works starting and ending, and what the person newly chose to keep in mind

- Status: Proposed
- Date: 2026-10-31
- Scope: three more kinds of news in a report (ADR-0356 §5:5), now that a work's briefing is rendered once and never re-rendered (ADR-0356 §5:2): the time the report was made (§2), each other work that started or ended since the exchange showed the concurrent stimuli (§3), and each pin or profile field the person changed since the exchange showed the person block (§4). What is deliberately not news (§5), the audience (§6), the instruction (§7) and who builds it (§8).
- Dependency: [ADR-0356](0356-the-system-briefs-planning-in-one-continuing-exchange-plannings-text-is-its-notes-and-an-episode-is-shown-by-its-short-view.md), whose exchange and news this decision adds to; [ADR-0359](0359-the-news-reports-a-matter-changed-and-a-memory-forgotten-since-the-work-was-shown-them.md), whose pattern it follows; [ADR-0349](0349-a-place-is-only-what-caused-an-activation-a-stop-is-reached-three-ways-running-work-is-shared-by-reading-it-and-the-newest-absorbs-what-it-continues.md), whose in-progress entries and peer view (§5, §6) it reports from; [ADR-0338](0338-a-person-sets-their-profile-and-pins-what-aether-always-keeps-in-mind-their-style-is-learned-as-memories-and-each-reaches-the-models-for-that-persons-activations.md), whose person block (§6, §7) it reports from; and [ADR-0353](0353-understanding-reads-its-stimulus-as-tagged-knowledge-then-memory-and-replies-with-what-it-understood-what-it-cites-what-is-unclear-and-where-it-belongs.md), whose times (§5) and entries (§2:5–§2:7) it renders as. All Accepted, as their status lines leave them.
- Authorization: on 2026-10-31 the owner, replying to the coordinator's pick that the news names other works starting and ending and gives the time, ruled, verbatim, "ok i like your pick", and then "yes" to recording them as ADR-0360 and building them in P3. Of memories the owner asked, verbatim, "should new memories also be added mid-work"; the coordinator's pick, to which the owner had not objected when this lane was dispatched, is that what the person newly chose for always in mind is news (§4) and newly committed long-term memories are not (§5). The owner refined the pick the same day, as the coordinator relayed it: a work that has ended is shown as short-term memory would show it, by its short view (§3:2), and planning's searches read the store as it now stands (§5:1). The coordinator assigned 0360, and ratifies it under the owner's delegation once its review is green (§1:1).
- **Not a contract-surface decision.** No Protocol and no `core` type changes: the news is rendered text in a report (ADR-0356 §5:3), and what it reads, the clock, the running activations and the person model, the phases already read. `PROTOCOL_VERSION` does not move under it.
- **Partially supersedes**, in the clauses §9's first table names: ADR-0356, ADR-0349 and ADR-0338.

## Context

ADR-0356 makes a work's rounds one continuing exchange whose briefing is rendered once (§5:2),
so a later round learns what changed from the news alone (§5:6). ADR-0359 added a matter
changed and a memory forgotten to the news. Three more things the briefing shows go stale
while a work runs.

- **The time.** The situation says when the briefing was made (ADR-0353 §6:1). A work can wait,
  on a slow call or on another work (ADR-0349 §7:26), and nothing later says what time it is.
- **Other works.** The concurrent stimuli section shows what else runs for the person when the
  briefing is made (ADR-0356 §3). A work that starts later, the person asking again on another
  channel, say, is invisible to this one, so both may handle it.
- **What the person chose.** Always in mind shows the person block as it was assembled, once
  per activation (ADR-0338 §7:1). A pin added or a field changed on the panel while the work
  runs reaches no later round, though the block's fields are the person's current choice and
  outweigh any other memory (ADR-0356 §10:5).

A **work**, a **report**, the **exchange** and the **news** are ADR-0356's (§Words). A thing
the work **was shown** is one the exchange showed it, in its briefing, a call's result or an
earlier news, as ADR-0359 has it.

## Decision

We will have each report's news begin with the time it was made, name each other work that
started or ended since the exchange last showed it, and name each pin and field the person
changed since. The briefing and every earlier turn stay as sent.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the adversarial review
> `CONTRIBUTING.md` → "Finishing an ADR PR" requires has returned green on one tree and the
> coordinator, under the owner's delegation, ratifies it. An assigned number or a green review
> alone does not change its status.

> **Normative.** No lane implements this decision before it merges `Accepted` (golden rule 5,
> ADR-0015 §5).

> **Normative.** Every earlier clause this decision replaces is replaced for an activation the
> phases plan, and for no other.

### 2. The time

> **Normative.** Each report's news begins with the time the report was made, read from the
> clock the pass already holds (ADR-0353 §6:2) and written as ADR-0353 §5:1 writes a time, in
> the zone the briefing's situation named, which it does not repeat (ADR-0353 §5:2).

> **Normative.** The time is not a change. A report whose news holds nothing else says that
> nothing else is new (ADR-0356 §5:5).

> **Normative.** Every time a work is shown is in the zone its briefing's situation named,
> for the whole work. A time zone the person changes while it runs is named as §4:3 says, and
> takes effect from the next briefing.

### 3. Other works starting and ending

> **Normative.** The news names each activation the concurrent stimuli section (ADR-0356 §3)
> would now enter and the exchange has not shown, by its `E` label, as that section renders an
> entry (ADR-0353 §2:5–§2:7), with its latest understanding's meaning where one is recorded,
> rendered as the peer view renders it (ADR-0349 §6:9), and says that it is being worked on
> separately.

> **Normative.** The news names each activation the exchange showed as running that has ended
> since as short-term memory would show it: under its `E` label, as its short view (ADR-0356
> §9), with that view's filters (ADR-0356 §9:5, §9:6) and its `ended` attribute, its input an
> empty `input` pointing at where the exchange showed it (ADR-0356 §9:1, §3:2). So the work
> holds what a fresh briefing's short-term memory would, and nothing is re-rendered.

> **Normative.** Which activations §3:1 names is the section's rule: the same person, the
> disclosure predicate and the Task Scheduler's activations (ADR-0349 §5:2–§5:5). A report
> names at most `in_progress_limit` newly started, newest first, and says how many more started
> (ADR-0349 §5:10).

> **Normative.** An activation another kind of news already names in the same report is not
> named again by this one: an offer newly open names the activation offering it, and the
> finished work newly read of one the work absorbed, took over or waited on shows its ending
> (ADR-0356 §5:5, §5:6), and is not shown again as a short view. One this work's own stop call
> ended is reported by that call's result.

> **Normative.** Planning reads more of a running activation named so through ADR-0350's list
> pull and the findings look-up its running part opens (ADR-0349 §6:1, §6:2), and of an ended
> one through the episode look-up (ADR-0358 §10).

> **Normative.** For planning's exchange, ADR-0349 §5:2's *understanding alone* and §5:9's
> *Planning is not shown the section* read as ADR-0356 §3 and this section have them: planning
> is shown the section in its briefing and its starts and ends in the news. ADR-0349 §5:1's
> *No rule pushes one activation's findings into another's* gains one exception, this
> section's news: a started activation's entry and meaning (§3:1), and an ended one's short
> view (§3:2), each under the section's rules and the view's filters. None of the three is
> replaced for any other stage, and no other rule pushes findings.

**Why.** A new input starts its own activation (ADR-0349 §8). Where it continues this work's
matter after this work acted, it reaches this work as an offer, which is already news; where
it does not, it is a separate work, and without this nothing tells this one that a separate
work already has it. An ended work is shown as its short view so that planning knows what it
did, and does not do it again or count on it still running.

### 4. What the person newly chose

> **Normative.** The news names each memory the slot would now show as pinned that the
> exchange has not shown pinned, as always in mind renders a pinned memory, under its `M`
> label (ADR-0338 §6:2, §6:4, §6:5); each memory the exchange showed pinned that no pin now
> reaches, by its label, as no longer pinned; and each profile field changed, with its new
> value as the block renders that field, or as not set.

> **Normative.** Pinned is read per memory, as the slot resolves pins: each pin to the current
> memory its chain reaches (ADR-0338 §4:8), each memory once. A memory two pins reach stays
> pinned until neither does, and a pin added to a memory already shown pinned is no news.

> **Normative.** The time zone, which always in mind does not render (ADR-0353 §4:5), is named
> with its new zone as the situation names one, saying that this work's times stay in the zone
> its briefing named (§2:3).

> **Normative.** Before each round after the first, code reads the person's profile and pins
> from the person-model store, with no model call, beside ADR-0338 §7:10's check, and compares
> them with what the exchange has shown. The block is not reassembled, and §7:10 is unchanged.

> **Normative.** A pin or field changed by this work's own call comes back in that call's
> result and is not named again (ADR-0356 §5:6). A memory forgotten is ADR-0359 §3's, not this
> section's.

**Why.** Pins and fields are the person's own explicit choices, the block's fields outweigh
any other memory (ADR-0356 §10:5), and a work that ignores a choice made a minute ago reads as
not listening. **The cost, plainly:** §7:10's check reads only the memory store, for the
memories the block already holds (`still_held`, `orchestration/person_block.py`), so this is
one more read, of the person-model store, before each later round.

### 5. What is deliberately not news

| Not news | Why |
| --- | --- |
| A long-term memory committed while the work runs | Recall chose for this stimulus at the start, a new memory's relevance to it is unknown, and recalling again each round costs and adds noise. Planning searches memory when it needs more (ADR-0307 §6:6), and past episodes (ADR-0358 §7) |
| A style memory marked, or a suggestion made, while the work runs | Learned, not chosen by the person, so §4's reason does not reach it |
| Whether a reply can still be written at the origin, and the place list | A `text` that cannot go comes back saying why and where it may go (ADR-0357 §2:5, §3:1) |
| When the person last sent a stimulus | A new stimulus at the origin is already news, as an offer or a stimulus taken in (ADR-0356 §5:5), and one elsewhere is a work starting (§3:1) |
| An edit or a deletion of an origin item already shown | Rare. Known, and not decided here (§10) |

> **Normative.** A memory search (ADR-0307 §6:6) or an episode search (ADR-0358 §7) planning
> runs during a work reads the store as it stands when the search runs (ADR-0282 §2:6), so a
> memory committed or an episode frozen since the work began is found there.

### 6. Audience

> **Normative.** Every kind is told only as the pass's audience may be shown it, as ADR-0359
> §5 has the pattern. A work is named only where the section's disclosure predicate admits it
> (ADR-0349 §5:4), its input in brief through the peer view, outside input withheld
> (ADR-0353 §2:7), and each item carrying its mark as the peer view gives it. An ended work's
> short view applies its own audience and outside filters (ADR-0356 §9:5, §9:6), and a work
> shown one resting on outside content has read outside content.

> **Normative.** §4 applies only to an activation the person block reaches, its person's own
> (ADR-0338 §7:1, §7:3). A new pin's memory is shown only under the slot's rules: no memory
> resting on outside content, and the record rule applied (ADR-0338 §6:4, §6:5).

### 7. The instruction

> **Normative.** ADR-0356 §5:7 is unchanged, and the instruction gains no sentence for any
> kind: "anything that changed since" covers all three, and the news line itself says a new
> work is being worked on separately.

### 8. Delivery

> **Normative.** No lane of its own builds this decision: ADR-0356's P3 builds all three
> kinds, under its fence (ADR-0356 §14:3).

> **Normative.** P3's tests include: each report's news begins with its time, in the
> briefing's zone; a work started between rounds is named once, in the next report, with its
> meaning, and one ended is shown once as its short view, under that view's filters, with its
> input pointed at and not repeated; a pin added between rounds is named
> once with its words, and a field changed once with its new value; of two pins reaching one
> memory, removing the first is no news and removing the second names it no longer pinned;
> and the briefing stays
> byte-identical across rounds.

### 9. Relationship to earlier decisions

Superseded in part. Every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0356 | §5:5, in the addition alone: the news also begins with the time, and names each other work started or ended and each pin or field the person changed since it was shown | §2, §3, §4 |
| ADR-0349 | §5:2's *understanding alone* and §5:9's *Planning is not shown the section*, for planning's exchange alone: planning is shown the section in its briefing (ADR-0356 §3) and its starts and ends in the news; §5:1's *No rule pushes one activation's findings into another's*, for planning's exchange and in the addition alone: the news shows a started activation's entry and meaning and an ended one's short view | §3:6 |
| ADR-0338 | §7:1's *The same block reaches every planning round*, in the addition alone: a pin or field the person changed since reaches the later rounds of the work as news | §4:1, §4:2, §4:4 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0356 §5:2, §5:6, §5:7 | Nothing: the briefing is rendered once, each change is said once, and "anything that changed since" is what the news carries |
| ADR-0359 §2, §3, §5 | Nothing: a changed matter and a forgotten memory are its, and its audience pattern is followed |
| ADR-0338 §3:6, §7:10 | Nothing: a work's times are read in the person's zone as its briefing found it, and §7:10 still drops a forgotten memory before each round |
| ADR-0349 §5:6, §5:10, §6:1, §6:9 | Nothing: an entry shows what it showed, under the same limit, and the findings look-up is opened as before |
| ADR-0356 §9 | Nothing: an ended work is shown as the short view short-term memory shows, with its filters |
| ADR-0307 §6:6, ADR-0358 §7, ADR-0282 §2:6 | Nothing: planning's searches read the store as it now stands |
| ADR-0353 §5, §6 | Nothing: a time is written as it was, and the zone is said once |

> **Normative.** This numbered draft records its replacements on the status lines and in a dated
> header note of ADR-0356, ADR-0349 and ADR-0338, atomically with this ADR under ADR-0070 and
> ADR-0082, preserving their ratified bodies. The replacements take effect on this ADR's
> ratification.

### 10. What this decision does not decide

| Not decided here | Where it goes |
| --- | --- |
| An edit or a deletion of an origin item the work was shown | A later decision, on evidence that it matters |
| Whether a shown work having acted since is news | A later decision, on evidence |

> **Normative.** Each item the table names takes a decision of its own before any lane builds
> it.

## Consequences

- A work knows the time, what else is running for the person, and what the person chose,
  without its briefing changing, so the cache holds.
- The news grows by a line each report for the time, and a line for each work started or
  ended and each choice changed, said once.
- Each later round reads the person-model store once more (§4:4).
- A work that ran across a time-zone change shows its old zone to the end (§2:3).

## Alternatives considered

- **Re-render the briefing when the time, the running work or the block changes.** Rejected:
  it breaks ADR-0356 §5:2 and the cache, as ADR-0359 found for its kinds.
- **Report newly committed memories too.** Rejected for now, for §5's reasons; the owner's
  question stays open to evidence that a work misses one it needed.
- **Report only a pin added, not one removed.** Not taken: a removed pin is as much the
  person's choice, and the briefing would go on showing it pinned.
- **Switch a work's times to a new zone mid-work.** Not taken: one exchange in two zones is
  harder to read than one in its briefing's zone, and the change is rare.
