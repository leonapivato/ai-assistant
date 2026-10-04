# 289. A story store holds which experiences belong to the same matter

- Status: Proposed
- Date: 2026-10-04
- Scope: [M40](https://github.com/leonapivato/ai-assistant/milestone/7), the story capability.
- Dependency: ADR-0286 and ADR-0287, implemented at `032b30d1`.
- Authorization: the owner worked out the design of stories between 2026-10-02 and 2026-10-04, recorded as direction on the wiki's Stories page, and on 2026-10-04 delayed forgetting stories to a later milestone. The same day the owner accepted proposal #2672 ("looks good"), including its recommendation that M40 build no producer in the hub, and the dispatcher assigned 0289, the next number on `main`. That authorizes drafting and numbering, not ratification or implementation.

## Context

The wiki's [Stories](https://github.com/leonapivato/ai-assistant/wiki/Stories) page,
read at wiki revision `1ea646c`, describes a **story** as the assistant's memory of
which experiences belong to the same matter. The windows find what is recent, recall
finds what is similar, and stories find what belongs. The owner's direction on that
page, which this ADR builds the first part of, is:

- **A link says only that a member belongs,** who linked it and when. It carries no
  type such as *changes* or *approves*, because one input can do several things to a
  matter ("make it Sunday, then yes").
- **Members are activations' episodes and other stories, and nothing else.** A
  smaller matter belongs to a larger one the way an episode does. Beliefs reach a
  story through what they are about and the episodes they cite. Timers, watches and
  effects point at stories without being members.
- **Merge and split.** Two stories found to be one matter are merged, and the absorbed
  story keeps its identity, marked as merged into the other. A story found to hold two
  matters is split.
- **No loops.** A link that would make a story contain itself is refused. A loop can
  mean that the two stories are one matter, that only some moments are shared, that
  they are two intertwined matters a larger story holds, or that the link is a mistake.
  Only whoever was linking can tell these apart.
- **A clean view and a change log.** Readers take the current membership. Every
  change appends a line of identities only, saying who made it, when and what
  triggered it, so nothing forgotten can survive in free text.
- **A story holds no text, no state and no authority.** What is learned about the
  matter, a summary included, is a belief about the story, kept outside it.
- **Membership changes nothing about who may see an episode.**
- **Forgetting stories is delayed** to a later milestone on forgetting, with the
  deferred cascade to beliefs (ADR-0287 §4).

The code at `032b30d1`:

- **Each store is its own SQLite file** in the data directory, built in
  `app/composition.py` behind a Protocol in `core/protocols.py`, as
  `SqliteParkedReads` is on `parked_reads.db`.
- **An episode is the record at `activation:<activation_id>`.** It is written open at
  admission (ADR-0286 §2), and `MemoryStore.get` reaches it while open (ADR-0286 §6).
  So whether an activation has an episode can be read while it runs.
- **`ActivationLinks`** carries today's turn loop's goal, attempt, question and park
  relationships on the processing record. The direction moves those relationships to
  stories when the planning and authorizing phases replace the turn loop. Nothing here
  touches them.
- **Episode inspection** is `AssistantEngine.episodes` and
  `AssistantEngine.episode_chunk`, rendered by `interfaces/episode_inspection.py`,
  which labels an open episode in progress (ADR-0286 §11).

No phase can produce a story yet. The planning phase that would start one is not
built, and today's turn loop will be replaced rather than extended. Timers, watches
and judgment linking by understanding are later milestones. So this decision builds
the store, the engine surface over it and a CLI that exercises it, and no producer
in the hub.

## Decision

### 1. The story store

> **Normative.** `core/protocols.py` gains a `StoryStore` Protocol. It is implemented
> in `memory/` by a SQLite store on its own file, `stories.db`, in the data directory.

> **Normative.** The Protocol ships as a triad, in one change with its SQLite
> implementation (ADR-0137 §2): the Protocol, a conformance suite at
> `tests/memory/story_store_contract.py`, and a canonical fake in
> `ai_assistant.testing`.

> **Normative.** The story store reads no other store. It holds identities and
> checks only what its own records decide.

### 2. Stories and members

> **Normative.** A story is identified by a `story:` id the store mints when it
> creates the story. It carries the instant it was created and, once merged, the id of
> the story it was merged into. It carries no title, summary, state, owner or text of
> any kind.

> **Normative.** A member is exactly one of two kinds: an activation, named by its
> activation id, or a story, named by its story id. The kind is carried with the id
> and never inferred from it.

> **Normative.** The store keeps the **clean view** as its own record: for each story,
> its current members, each with the instant it was linked and the actor that linked
> it, in the order they were linked.

> **Normative.** The store keeps the **change log** as an append-only record. Each
> line carries a sequence number unique across the store, the story changed, what
> happened, the member where there is one, the story on the other side for a merge or
> a split, the actor, an optional triggering activation id, and the store's clock
> reading. No line is ever rewritten or removed.

> **Normative.** What happened is a closed enumeration, added to and never renamed,
> whose members are `created`, `added`, `removed`, `merged_into`, `absorbed` and
> `split_off`.

> **Normative.** The actor is a closed enumeration, added to and never renamed. This
> ADR gives it one member, `owner`. A later decision that builds a producer adds that
> producer's member.

> **Normative.** No field of a story, a view entry or a log line holds free text.

> **Normative.** Every operation that changes a story writes the clean view and the
> change log in one transaction. Either both change or neither does, and a refused
> operation writes nothing.

### 3. Operations

> **Normative.** **Create** takes one or more members, an actor and an optional
> triggering activation id. It mints the story and logs `created`, then each member
> as `added`. Create with no members is refused. The store does not require two
> members: whether something connects moments is the linker's judgment.

> **Normative.** **Link** adds members to a story, each logged as `added`. A member
> already in the story is passed over, with no log line.

> **Normative.** **Unlink** removes members from a story, each logged as `removed`. A
> member not in the story is passed over, with no log line. A story left with no
> members stays as a story with no members.

> **Normative.** **Merge** of story A into story B moves A's members to B: each is
> removed from A, logged on A as `removed`, and added to B where B does not already
> hold it, logged on B as `added`. A member B already holds keeps its existing entry,
> with its link instant, actor and place in the order. A is left with no members.

> **Normative.** A merge logs `merged_into` on A and `absorbed` on B, each naming the
> other. From then on A records B as the story it was merged into.

> **Normative.** A merge removes A from every story that held it, logged on each as
> `removed`. It adds B to each such story that does not already hold B and is not B
> itself, logged as `added`. A story that already holds B keeps that entry as it was.

> **Normative.** Where B was itself a member of A, a merge of A into B removes that
> member from A and adds nothing for it, instead of making B contain itself.

> **Normative.** A merge that would leave any story containing itself through any
> chain of stories, after those exceptions, is refused.

> **Normative.** A merge of a story into itself is refused.

> **Normative.** **Split** of story A takes a non-empty subset of A's current members
> and mints a new story C. It removes them from A and adds them to C, logged on A as
> `removed` and on C as `created` and `added`, with `split_off` on both naming the
> other. C is not made a member of A.

> **Normative.** A write to a merged story, or one naming a merged story as a member,
> is refused, and the refusal names the story it was merged into.

> **Normative.** A link that would make a story contain itself through any chain of
> stories is refused. The refusal names the stories forming the loop. The
> store never merges, re-links or drops a link to resolve one.

> **Normative.** A write naming a story the store does not hold, as the story written
> to or as a member, is refused.

> **Normative.** The store answers five reads and no others:
>
> - a story's header, its id, creation instant and the story it was merged into;
> - its clean view, page by page, in link order;
> - its change log, page by page, in sequence order;
> - every story, page by page, newest first;
> - the stories a member belongs to directly.

Reading a merged story returns its header, so a caller follows it to the story it was
merged into. The stories a member belongs to directly is the reverse lookup that the
episode detail needs now, and that the forgetting milestone and the readers of beliefs
about a story will need later.

> **Normative.** Each refusal is reported as a typed outcome carrying a closed
> enumeration of reasons, not as a store failure. `StoryStoreError` is raised only
> where the store could not read or write its file.

### 4. The engine surface

> **Normative.** `AssistantEngine` gains methods to create a story, link, unlink, merge
> and split, and to read a story's view, its change log, the list of stories and the
> stories an activation belongs to. They are added to `Engine`, the canonical fake
> engine and the wire client, and the change advances `PROTOCOL_VERSION`.

> **Normative.** Before a write that adds an activation member, the engine reads
> `activation:<activation_id>` through `MemoryStore.get`, and refuses the write where
> no record is there. An open episode is a record there (ADR-0286 §6), so a running
> activation can be linked.

> **Normative.** Every write the engine makes carries the actor `owner` and no
> triggering activation.

> **Normative.** The engine's read of a story's view resolves each activation member
> to its episode's `EpisodeSummary`, or marks it **forgotten** where no record is
> there any more. It resolves each story member to its id and its current member
> count, one level deep.

> **Normative.** No stage, phase, rule or prompt reads or writes a story, and no read
> that feeds a model includes one.

> **Normative.** Forgetting a record, forgetting a conversation and retention change in
> nothing. An activation id whose episode is gone stays in every story that holds it,
> and no story is deleted.

### 5. The CLI

> **Normative.** The CLI gains a `story` command group to create a story, link,
> unlink, merge, split, list stories and show one. A member is written as an activation
> id or a story id. The group is for testing, and its help says so.

> **Normative.** `story show` renders the story view:
>
> - each activation member by the one-line summary the episode list renders, labelled
>   in progress where its episode is open and **forgotten** where it is gone;
> - each story member nested, one level deep, by its id and member count;
> - the change log after the members, oldest first;
> - for a merged story, only the line naming the story it was merged into.

> **Normative.** The episode detail gains one line naming the stories the episode's
> activation belongs to directly, or saying it belongs to none.

> **Normative.** No browser or gateway surface reads or writes stories.

### 6. Delivery

> **Normative.** Land this ADR ratified before any implementation lane. Then the
> implementation ships as three PRs:
>
> 1. **`core`, `memory` and `testing`**: §1 to §3, the triad with its SQLite
>    implementation;
> 2. **the engine surface**: §4, across `AssistantEngine` in `core`, `Engine` in
>    `orchestration`, the wire client, the canonical fake engine, and the composition
>    in `app` building `stories.db`;
> 3. **`interfaces`**: §5.

> **Normative.** Lane 2 lands after lane 1, and lane 3 after lane 2, because each
> calls what the one before adds.

Deploying it adds `stories.db` and changes no existing record, so the hub keeps its
data directory.

## Consequences

**What becomes possible.** A story can be built, grown, merged, split and inspected
across many activations, and loops are refused. The store's rules can be exercised
before any phase depends on them, and the planning phase, timers and watches, and
understanding each build against a contract that already holds. Each of them adds its
own actor member when it starts producing stories.

**What it costs.** A new store, a new file in the data directory, nine engine methods
on the wire and a CLI group, with nothing in the hub using them yet. That is accepted:
the store's rules are where the design risk is, and they are testable on their own.

**What stays open.**

- **Forgetting stories, and forgetting reaching into them,** are delayed to the
  forgetting milestone, with the rules already on the wiki. Until then, a forgotten
  episode's activation id stays in its stories and renders as forgotten, as a belief
  citing a forgotten episode keeps its id (ADR-0287 §4).
- **Which phase reads a story, and how much,** is that phase's design.
- **Beliefs about a story** need a belief to be able to name a story as its subject.
  That is the memory side's change, made when observation is rebuilt.
- **Whether the owner's export includes stories** is left to the forgetting
  milestone, which decides how a story leaves. `stories.db` goes wherever the data
  directory goes, backups included (ADR-0123).
- **Members ordered by when they happened.** The store keeps link order because it
  cannot see episodes. A reader that wants time order sorts by each episode's own
  `occurred_at`.

**Alternatives rejected.**

- **Stories in the memory store.** It would make a later forget cascade one
  transaction, but forgetting is delayed. The story store is a graph with its own log,
  and `MemoryStore` is already the largest contract. The forgetting milestone can
  revisit this.
- **The store checks that activations exist.** That would build the story store with
  the memory store injected, coupling two independent stores. The engine already holds
  both and already knows how an open episode is read.
- **The view replayed from the log.** Every read would replay. Writing both in one
  transaction keeps them equal.
- **A loop merged automatically.** A loop can mean four different things, and only
  the linker can tell them apart (owner direction, 2026-10-03).
- **Planning as M40's first producer.** The planning phase is not built, so the
  producer would have nothing to run in (owner, 2026-10-04, accepting #2672).
