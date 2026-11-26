# 384. Upkeep of a person's records runs for that person: a run tends one domain, reads what its person may see through the filter, and writes only there

- Status: Accepted
- Date: 2026-11-26
- Scope: decision D2 of milestone 22, "Every record has a home" (acceptance
  [#3709](https://github.com/leonapivato/ai-assistant/issues/3709)), its row "Upkeep still works".
  For a hub with one person, it decides which of the system's own upkeep jobs it covers (§2),
  whose sight bounds a run's reads (§3), where its writes land (§4), that a run keeps to one domain
  (§5), what bounds a tidy-up a work asks for (§6), and that every such read goes through the one
  filter (§7). §8 says how it stands to ADR-0368 §3:7, §9 what it does to earlier decisions, §10
  what building it needs, §11 what it settled beyond the rulings, and §12 what it leaves to others.
- Authorization: the owner's words, verbatim. On 2026-11-23, "Yes, scope milestone 1", to "Do you
  accept the five-milestone order for the build plan?"; the order is in #3709's first paragraph.
  On 2026-11-26, "Yes, agreed", to "Do you agree this scope: "Yes, agreed" or "Change something"?",
  the scope being what #3709 records. With that question the owner was shown, twice, the
  coordinator's sentence "My pick is that upkeep of a person's records runs for that person." They
  did not object to it and did not rule it by itself, so it is this decision's own (§11). The
  coordinator assigned 0384 and ratifies it, under the owner's delegation, once its review is green.
- **A decision only, not contract-surface.** This document changes no Protocol, type, field or
  code, names no `core` change, and supersedes nothing of ADR-0368 (§8), so it takes the
  adversarial review.
- **Partially supersedes**
  [ADR-0304](0304-a-storys-page-is-its-summary-shown-where-owner-records-are-a-lookalike-is-not-read-and-a-story-is-a-referent.md)
  (§4:4, in its first sentence alone) and
  [ADR-0358](0358-planning-keeps-memory-only-on-purpose-a-matter-that-has-changed-is-tidied-in-the-background-and-planning-can-search-past-episodes-read-one-whole-and-read-its-origins-older-history.md)
  (§4:5, in the addition alone), as §9 records.

## Context

[ADR-0369](0369-a-record-lands-in-the-domain-of-whom-its-work-is-for-sharing-rules-open-a-domain-and-default-to-private-every-read-is-filtered-to-who-may-see-and-each-person-sees-deletes-and-exports-their-own.md)
§10:5 puts one filter on "every read a work's stages make" and on "every read a producer makes for
a work after it has ended". The story tidy-up and the matters pass are neither. Each calls itself
"an operation on the assistant's own records" (`StoryTidyUp`, `MattersPass`), and neither is an
activation (ADR-0358 §4:7, ADR-0300 §9:3). They read a person's stories and episodes, search the
memory store, and rewrite, merge, split and move. Nothing decided says whose sight bounds those reads
or where those writes land. ADR-0304 §4:4 says only that the two "apply no reader's rule". If they
were works for no one, ADR-0369 §10:1 would give them "the records of the hub's shared things, and
what anyone may see": nothing of the owner's. So once the filter decides, the jobs that tend the
owner's records would read none of them, or would have to go round the filter.

As built at `9c91f4e92`, `service.scheduler.jobs_for` arms seven rows: `retention_purge`,
`conversation_sweep`, `notification_reconsider`, `calendar_upcoming`, `observer`,
`scheduled_tidy_up` and `matters_pass`. `Engine.start` also closes the episodes a dead process left
open, reconciles the outbox, and starts the channels' readers and sensors. A work's end removes
finished tasks (`TaskManager.tidy`) and voids an approval's tickets (`Engine._void_tickets`).
Planning's tidy-up call runs the same `StoryTidyUp` inside a work (`orchestration/story_calls.py`).
The notification store's one producer is `UpcomingEventStage`, which reads the owner's calendar.
The offline tools (backup, restore, purge, re-embedding, store health, measures) are console
scripts a person runs under the instance lock.

**Words.** A **domain**, the **hub's shared things** and **the filter** are ADR-0369's (§2, §10:5);
a **work** is ADR-0368's, an activation. **Upkeep** is ADR-0368's word: what the system does to its
own records with no person asking. An **upkeep job** here is upkeep that is not a work and reads
records out of a store, to show them to a model or to write a record from them. A **run** is what
one invocation of a job does, from finding what is due to its last write. A run **tends** the
domain whose records it reads and writes. A bare section reference, such as §3:1, is to this
decision's own clauses.

## Decision

We will have each run of an upkeep job tend one domain, read through the filter no more of it than
that domain's person may see, write only there, and treat any other domain's record as absent.

### 1. Status and scope

> **Normative.** No lane implements against this decision before it merges `Accepted` (golden
> rule 5, ADR-0015 §5).

> **Normative.** This decision takes effect for a job's writes once records carry their domain
> (ADR-0369 §2:1), and for its reads once ADR-0369 §10's filter decides reads. Until then each
> job reads and writes as it does today.

> **Normative.** This decision rules the owner's domain and the hub's shared things, the two
> domains of a hub with one person. Upkeep over a group's domain, or over the domain of a person
> other than the owner, is left to the decision that admits them.

### 2. The jobs it covers

> **Normative.** This decision covers three upkeep jobs: the story tidy-up (ADR-0300 §5, ADR-0303
> §5, ADR-0304), run on ADR-0358 §4's schedule or by planning's call; the matters pass (ADR-0300
> §9:3, ADR-0302 §5); and the notification reconsideration (ADR-0130 §5).

> **Normative.** An upkeep job a later decision adds is covered by this decision, unless that
> decision rules otherwise.

| What runs | Where it starts | Covered | What rules it |
| --- | --- | --- | --- |
| The story tidy-up, scheduled | `scheduled_tidy_up` row | Yes | §3 to §5, §7 |
| The story tidy-up, planning's call | acting, in a work (`story_calls`) | Yes, as that work's read | §6, ADR-0369 §10 |
| The matters pass | `matters_pass` row | Yes | §3 to §5, §7 |
| The notification reconsideration | `notification_reconsider` row | Yes | §3 to §5, §7 |
| The observer | each frozen episode; `observer` row | No: a producer for a work that has ended | ADR-0369 §2:2's first sentence, §10:5 |
| The upcoming-event producer | `calendar_upcoming` row | No: it reads a source, not a store | ADR-0369 §2:2's second sentence |
| Retention purge; conversation sweeps; closing open episodes; the outbox's reconciliation; removing finished tasks; voiding tickets | rows above; `Engine.start`; a work's end | No: each selects records by a deadline, a stamp or a state and reads nothing of their content | Unchanged |
| The channels' readers and sensors | `Engine.start` | No: each starts works | ADR-0369 §10, for those works |
| The offline tools | a console script | No: a person runs each, so none is upkeep | Unchanged (§12) |

### 3. Whose sight bounds a run's reads

> **Normative.** Upkeep of a person's records runs for that person: a run tends one domain, and
> reads no more of it than that domain's person may see (ADR-0369 §6).

> **Normative.** A run that tends the hub's shared things reads no more of them than the owner may
> see (ADR-0369 §2:8, §6:1).

> **Normative.** Tending a domain makes no job a work. A run records none of ADR-0368 §2's three
> facts, starts no activation, records no episode and makes no call the check runs, and each job
> stays what its own decisions make it.

> **Normative.** The notification reconsideration re-rules only held notifications of the owner's
> domain, in the owner's zone (ADR-0338 §3:6). A held notification of another domain is left to the
> decision that rules whom such a notification goes to.

A model call a job makes stays processing (ADR-0292 §12:4), and nothing here changes which route it
calls. With one person §3:1 withholds nothing the jobs read today: after the upgrade every earlier
record is the owner's (#3709), and ADR-0369 §6:1 lets a person see the whole of their own domain.

Tested against each job, the rule holds for the tidy-up and the matters pass, which each work on
one story or one flag at a time. It holds for the reconsideration only because that job's one
producer writes into the owner's domain (ADR-0369 §2:2): a notification is re-ruled in the zone of
whoever it goes to, which is not a fact of its domain, hence §3:4. It breaks for a group's domain,
which has no one person (§1:3). And it would break for the observer: an unidentified sender's work
is for whoever its connection belongs to (ADR-0368 §3:3), so its episode is the owner's, but it
reads nothing of the owner's (ADR-0369 §10:2). Bounded by §3:1, the observer would read the owner's
whole domain for that episode. ADR-0369 §10:5 bounds it by the work's sight instead, which is why
§2 leaves it out.

### 4. Where a run's writes land

> **Normative.** Every record a run writes lands in the domain the run tends.

> **Normative.** A run's write changes only records of the domain it tends, and places a proposal
> only against memories of it, as ADR-0369 §2:6 and §2:7 rule for a work's. A change a run chose
> that names a record of another domain is refused, and nothing of it is written.

### 5. One domain to a run

> **Normative.** No run reads or changes records of two domains. A job that tends both domains does
> so in a run for each.

> **Normative.** A record of another domain is absent to a run, as a record the filter withholds is
> absent to a work (ADR-0369 §10:6): the run reads, shows, counts and names nothing of it, and
> changes nothing of it.

> **Normative.** The matters pass decides no flag one of whose stories is of another domain: it
> makes no completion for that flag and writes nothing for it.

So the tidy-up's *looks like another story* flag is shown only stories of its domain, those its
episodes belong to and those the search finds alike, and can name no other. A member of another
domain is not taken in, as a member the memory store no longer holds is not. A decision recorded
for a story is shown only by the stories of the run's domain it concerns. Under ADR-0369 §2:6 no
link joins two domains' records, so a run meets one only where a record already says so in error;
§5:3 says what the pass does then, which absence alone would not settle.

### 6. A tidy-up a work asks for

> **Normative.** A tidy-up that planning's story call runs inside a work reads as every read of that
> work does, no more than the work may see (ADR-0369 §10:1 to §10:5), and of that only records of
> the story's domain.

> **Normative.** Planning's tidy-up call runs only on a story of the domain that work's records land
> in (ADR-0369 §2:1). On a story of any other domain it is not done and writes nothing.

§6:2 is ADR-0369 §2:1 and §2:6 applied to the call: a work for the owner may see the hub's shared
things, but what it writes lands in the owner's domain, so it cannot rewrite a story of theirs. The
tidy-up a work runs is part of that work, which is for whom it is for, and not upkeep run as a work.

### 7. Through the one filter

> **Normative.** Every read a run makes, its finding of what is due included, goes through the one
> filter ADR-0369 §10:5 names, under the sight §3 or §6 gives it, and no upkeep read goes round it.

> **Normative.** No model takes part in bounding a run's reads, and no rule rests on a model
> keeping back something it was shown (ADR-0369 §10:8).

### 8. How this stands to ADR-0368 §3:7

ADR-0368 §3:7 rules upkeep that "runs as a work". A work is an activation, and none of the jobs §2:1
covers is one: the scheduled tidy-up "starts no activation, records no episode" (ADR-0358 §4:7),
and the matters pass's changes are "background maintenance" (ADR-0300 §9:3). ADR-0368 says so
itself, beside §3:7: "Upkeep the corpus already runs outside planning, such as ADR-0358's tidy-up,
is not a work and is unchanged." So §3:7 does not bear on today's upkeep, and this decision
supersedes nothing of ADR-0368. §3:7, and §7:5's exception for "an upkeep job's own calls", stay for
upkeep a later decision runs as a work; `WorkForKind.NO_ONE`'s "the system's own upkeep" names that
case, and no such work exists.

### 9. Relationship to earlier decisions

> **Normative.** This decision partially supersedes ADR-0304 §4:4, in its first sentence alone: the
> tidy-up and the matters pass read through the filter, under the sight §3 and §6 give them. Its
> second sentence stands, for the records of the domain a run tends.

> **Normative.** This decision partially supersedes ADR-0358 §4:5, in the addition alone: what a
> scheduled tidy-up reads is also bounded by §3, §5 and §7.

> **Normative.** This numbered draft records its replacements on ADR-0304's and ADR-0358's status
> lines and in a dated header note on each, atomically with this ADR under ADR-0070 and ADR-0082,
> preserving their ratified bodies. The replacements take effect on this ADR's ratification.

| Clause | What this decision does |
| --- | --- |
| ADR-0304 §4:4 | Partially supersedes it (§9:1) |
| ADR-0358 §4:5 | Partially supersedes it (§9:2) |
| ADR-0368 §3:7, §7:5 | Does not bear (§8); no record |
| ADR-0369 §2:6, §2:7, §6:1, §10:6, §10:8 | Applies their rule to runs by its own clauses (§4, §5, §7); no record |
| ADR-0369 §2:2, §10:5 | Rule the observer and the upcoming-event producer (§2); no record |
| ADR-0300 §5, §9:3; ADR-0302 §5; ADR-0303 §5:7; ADR-0130 §5 | Read through: the filter narrows what they read and changes no clause of them, as ADR-0369 §10:5 narrows recall with no record on recall's decisions |

### 10. What building it needs

The build hands each covered job the domain a run tends and has its reads asked of the filter under
§3's sight; the seam and its types are the contract decision's, and this decision names neither. The
scheduled tidy-up, the matters pass and the reconsideration each run once for each domain on their
row; the order of those runs, and how they share `scheduler_run_budget`, are the build's. Planning's
tidy-up call gains the refusal §6:2 names; its reason's text is the build's.

### 11. What this decision settled beyond the rulings

The owner ruled the milestones' order and #3709's scope. Everything below is this decision's: the
coordinator's sentence as §3:1; the shared things' sight (§3:2); which jobs are upkeep jobs and
which are covered (Words, §2); that a later job is covered (§2:2); that tending a domain makes no
job a work (§3:3); the reconsideration's limit (§3:4); where writes land (§4); one domain to a run,
absence and the matters pass's flag (§5); the bound and the refusal for planning's call (§6); the
finding of what is due through the filter (§7:1); the reading of ADR-0368 §3:7 (§8); when it takes
effect (§1:2); and the two partial supersessions (§9).

### 12. What this decision leaves to others

- **The contract decision for milestone 22's homes and filter:** the value that names a domain,
  which stores carry it, whose sight bounds a work's read, and where the filter sits.
- **The owner's acts** to see, delete and export (ADR-0369 §12): milestone 22's own lane.
- **The reach of what a run writes:** ADR-0369 §7:5 names works and producers; milestone 5.
- **A group's domain and another person's**, and whether an offline tool may reach a domain other
  than its runner's: the decision that admits them, milestone 5.
- **Whom a notification goes to**, for a held notification of another domain (§3:4): milestone 4.
- **Outside content** (ADR-0371), the tidy-up's rule for a story of nothing but outside content
  included; and what any job writes or how it decides, beyond which domain it may touch.

> **Normative.** This decision may not be cited to settle any matter §12's list leaves to another.

## Consequences

- On today's hub the jobs read what they read today, now through the filter, and none stops.
- A story of the shared things is never shown to a tidy-up of the owner's, nor merged with one.
- A story an unidentified sender's work starts lands in the owner's domain (ADR-0368 §3:3,
  ADR-0369 §2:1) and is tended with the owner's sight. Nothing a run writes from it reaches that
  sender, whose works read nothing of the owner's (ADR-0369 §10:2).
- **Revisit** when a second person or a group is admitted, or when a notification can belong to a
  domain other than the owner's.

## Alternatives considered

- **Make each run a work for the domain's person.** Set aside: it would record ADR-0368 §2's three
  facts, start an activation and record an episode, which counts toward the window the observer
  reads (ADR-0329 §7:3). Only the bound on reads is needed.
- **Run upkeep for no one, as ADR-0368 §3:7 rules for a work.** Set aside: ADR-0369 §10:1 would give
  it nothing of the owner's, and the owner's upkeep would stop.
- **Let upkeep read every domain, outside the filter.** Set aside: #3709 rules the old path gone.
  With a second person, tending one person's story would show a model another's, and a merge could
  cross domains.
- **Bound the observer the same way.** Set aside: §3 shows where it breaks; ADR-0369 §10:5 already
  rules it.
