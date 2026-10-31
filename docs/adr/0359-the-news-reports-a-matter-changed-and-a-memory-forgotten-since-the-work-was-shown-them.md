# 359. The news reports a matter changed and a memory forgotten since the work was shown them

- Status: Proposed
- Date: 2026-10-31
- Scope: what a report's news (ADR-0356 §5:5) adds now that a work's briefing is rendered once and never re-rendered (ADR-0356 §5:2): a matter the work was shown that has changed since (§2), and a memory it was shown that the memory store no longer holds (§3). How ADR-0338 §7:10 reads for a work's own exchange (§4), the audience the news is told under (§5), the instruction (§6), and who builds it (§7).
- Dependency: [ADR-0356](0356-the-system-briefs-planning-in-one-continuing-exchange-plannings-text-is-its-notes-and-an-episode-is-shown-by-its-short-view.md), whose exchange and news this decision adds to; [ADR-0338](0338-a-person-sets-their-profile-and-pins-what-aether-always-keeps-in-mind-their-style-is-learned-as-memories-and-each-reaches-the-models-for-that-persons-activations.md), whose §7:10 it reads for the exchange; [ADR-0307](0307-a-planning-round-is-one-model-response-that-writes-its-own-message-keeps-episode-notes-and-names-what-it-was-shown-by-label.md), whose labels (§5:1) and audience rule (§6:4) the news uses; and [ADR-0282](0282-phases-read-and-write-the-working-episode-and-recall-searches-past-the-windows.md), whose audience predicate (§2:8) every fetch applies. All Accepted, as their status lines leave them.
- Authorization: on 2026-10-31 the owner ruled, verbatim, on [#3536](https://github.com/leonapivato/ai-assistant/issues/3536), "go with your pick on 3536", the coordinator's pick being the news (its ruling comment records it); on a matter changed mid-work, replying to the coordinator's proposal, "yes add it to P3"; and on forgetting, "i didnt know we were dealing with forgetting, I think we can still defer this unless its simple here". It is simple here: it is the same check as the matter one, over the memories the person block is already re-read for before each round (`still_held`, `orchestration/person_block.py`), so it stays in ([#3531](https://github.com/leonapivato/ai-assistant/issues/3531)'s comment of 2026-10-31 widening P3). The coordinator assigned 0359, and ratifies it under the owner's delegation once its review is green (§1:1).
- **Not a contract-surface decision.** No Protocol and no `core` type changes: the news is rendered text in a report (ADR-0356 §5:3), and what it compares, the matters and memories a work was shown, the phases already hold. `PROTOCOL_VERSION` does not move under it.
- **Partially supersedes**, in the clauses §8's first table names: ADR-0356 and ADR-0338.

## Context

ADR-0356 makes a work's rounds one continuing exchange. The briefing is rendered once and
handed in byte for byte (§5:2), and a later round learns what changed from the news alone
(§5:6). The news lists offers newly open and closed, findings newly read and stimuli taken in
(§5:5), and planning's instruction says each round sees "anything that changed since" (§5:7).

Two things that change under a running work are on no list. A matter the briefing showed can
be tidied, given a note, merged, split or removed by another work or a background job, and the
briefing still shows it as it was. A memory the briefing showed can be forgotten, and ADR-0338
§7:10 requires that "a memory forgotten while the activation runs reaches no later request",
which a frozen briefing cannot meet. P2 found the second ([#3536](https://github.com/leonapivato/ai-assistant/issues/3536));
the coordinator found the first while briefing P3. P3 is
[#3551](https://github.com/leonapivato/ai-assistant/pull/3551), whose pre-flight flags that
the news it builds needs this record.

A **matter** is a story (ADR-0307 §5:1's `S` label). A thing the work **was shown** is one the
exchange showed it, in its briefing, a call's result or an earlier news.

## Decision

We will have the news name each matter the work was shown that has changed since, by its label
and with what happened, and each memory the work was shown that the memory store no longer
holds, as forgotten and not to be used. The briefing and every earlier turn stay as sent.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the adversarial review
> `CONTRIBUTING.md` → "Finishing an ADR PR" requires has returned green on one tree and the
> coordinator, under the owner's delegation, ratifies it. An assigned number or a green review
> alone does not change its status.

> **Normative.** No lane implements this decision before it merges `Accepted` (golden rule 5,
> ADR-0015 §5).

> **Normative.** Every earlier clause this decision replaces is replaced for an activation the
> phases plan, and for no other.

### 2. A changed matter

> **Normative.** The news also names each matter the work was shown that has changed since the
> exchange last showed it, by its `S` label, with what happened.

> **Normative.** What happened is each of these that has happened since: its summary was rewritten, with the
> new summary's first line; it gained a note; it was merged into another, named by that one's
> label; it was split; or it is gone, the story store holding it no longer.

> **Normative.** The news shows nothing more of a changed matter than §2:2 names. Planning reads
> the matter as it now stands with the story read it already has (ADR-0307 §6:6).

> **Normative.** The matter a merge went into is named by its label, which it takes there where
> planning holds none for it (ADR-0307 §5:1).

### 3. A forgotten memory

> **Normative.** The news also names each memory the work was shown that the memory store no
> longer holds, as ADR-0338 §7:10's check reads it, by its `M` label, as forgotten and not to be
> used.

> **Normative.** A forgotten memory names no words of its own in the news, only its label.

### 4. ADR-0338 §7:10, within a work

> **Normative.** Within a work, a memory the store no longer holds stays in the turns already
> sent, the briefing included, and is announced as §3:1 says instead of being dropped from them.
> This replaces ADR-0338 §7:10's *reaches no later request* for the later rounds of the work it
> was shown to.

> **Normative.** Code still drops the memory from the person block before each round (ADR-0338
> §7:10), so a briefing rendered after it is gone never holds it.

**The cost, plainly.** For the rest of the work that was shown it, a forgotten memory's words
are still in the request each later round sends to the provider, and in that round's recorded
request. Planning is told not to use it, but the model still reads it. This is the price of the
append-only exchange and its cache (ADR-0356 §5): dropping it would re-render the briefing, and
every round after would pay for the whole request again. A work is one activation's planning, so
the exposure ends with the activation.

### 5. Audience

> **Normative.** A change is announced only as the pass's audience may be shown that matter
> (ADR-0307 §6:4, ADR-0282 §2:8). On a pass that may not be shown records placed for the owner
> alone, a rewritten summary is said to be rewritten with no line of it, and a note gained is
> not said.

> **Normative.** The news gives no note's words and no outside content, only that the change
> happened. A rewritten summary marked as outside content (ADR-0307 §6:2) is said to be
> rewritten with no line of it.

> **Normative.** Where the pass may not be shown the matter a merge went into, the news says
> only that the matter was merged, and names nothing it went into.

### 6. The instruction

> **Normative.** ADR-0356 §5:7 is unchanged, and the instruction gains no sentence for either
> kind: "anything that changed since" covers both, and the news line itself says a forgotten
> memory is not to be used.

### 7. Delivery

> **Normative.** No lane of its own builds this decision: ADR-0356's P3 builds both kinds, under
> its fence (ADR-0356 §14:3).

> **Normative.** P3's tests include: a matter changed between rounds by another work is named
> once, in the next report, with its change; a memory forgotten between rounds is named as
> forgotten in the next report; and the briefing stays byte-identical across rounds.

### 8. Relationship to earlier decisions

Superseded in part. Every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0356 | §5:5, in the addition alone: the news also names a matter changed since it was shown, and a memory the store no longer holds | §2, §3 |
| ADR-0338 | §7:10's *reaches no later request*, for the later rounds of the work the memory was shown to: it stays in the turns already sent, and is announced | §4:1 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0356 §5:2, §5:6 | Nothing: the briefing is rendered once and never re-rendered, and each change is said once |
| ADR-0356 §5:7 | Nothing: its "anything that changed since" is what this decision makes the news carry |
| ADR-0338 §7:1 | Nothing: the block reaches every round except as §7:10 drops from it, and §7:10 still drops |
| ADR-0307 §5:1, §6:4 | Nothing: the news names by label, and follows the audience's views |
| ADR-0282 §2:6, §2:8 | Nothing: a fetch reads the current version under the audience, and a missing record is no error |

> **Normative.** This numbered draft records its replacements on the status lines and in a dated
> header note of ADR-0356 and ADR-0338, atomically with this ADR under ADR-0070 and ADR-0082,
> preserving their ratified bodies. The replacements take effect on this ADR's ratification.

## Consequences

- A work keeps sight of what moved under it without its briefing changing, so the cache holds.
- The news grows by a line for each changed matter and each forgotten memory, said once.
- A forgotten memory stays in front of the model for the rest of the work that was shown it
  (§4). Revisit this if a person's forgetting must take effect inside a running work, which
  would mean ending the work's exchange and briefing anew.

## Alternatives considered

- **Re-render the briefing when something in it changes.** Rejected: it breaks ADR-0356 §5:2
  and the cache, and a later round would no longer see its earlier rounds as they were.
- **Drop a forgotten memory from the turns already sent.** Rejected for the same reason: it
  edits an earlier turn.
- **Defer forgetting.** The owner's first inclination. Not taken, because it is the same check
  as the changed matter, over ids the phases already re-read.
