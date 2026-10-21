# 342. The memory store reads a memory by id whatever its status, so a pin follows its successors

- Status: Proposed
- Date: 2026-10-21
- Scope: one read on `MemoryStore` that returns memories by id whether they are current, ended or wrong, and the rules that bind its callers. The callers are the ones [ADR-0338](0338-a-person-sets-their-profile-and-pins-what-aether-always-keeps-in-mind-their-style-is-learned-as-memories-and-each-reaches-the-models-for-that-persons-activations.md) needs: its person block, the observer's pin pass and the panels. The gap is [#3308](https://github.com/leonapivato/ai-assistant/issues/3308), found by ADR-0338's lane 1 ([#3306](https://github.com/leonapivato/ai-assistant/pull/3306)). A rendered history of what Aether used to believe is not decided here (§7).
- Dependency: [ADR-0338](0338-a-person-sets-their-profile-and-pins-what-aether-always-keeps-in-mind-their-style-is-learned-as-memories-and-each-reaches-the-models-for-that-persons-activations.md), [ADR-0328](0328-a-memory-is-a-statement-resting-on-supports-its-standing-is-computed-from-them-and-every-change-to-it-is-an-operation-citing-one.md), [ADR-0073](0073-the-band-scoped-read-is-an-enumeration.md), [ADR-0045](0045-memory-records-carry-a-validity-window.md) and [ADR-0086](0086-a-beliefs-evidence-is-bounded-and-the-batch-read-lands.md), as their status lines leave them.
- Authorization: the coordinator decided this read under the owner's standing delegation. The owner's words on that delegation, verbatim: "Dont draw the line who ratifies what, Ill just check in and if I see something wrong I'll give input to you." The dispatcher assigned 0342, and ratifies it under that delegation.
- **Changes a `Protocol`, so it is a contract-surface decision and a breaking change under golden rule 5.** `MemoryStore` in `core/protocols.py` gains one member (§2:1). `core/types.py` gains nothing, because the read returns the memory type that already exists. The wire does not carry `MemoryStore`, so `PROTOCOL_VERSION` does not move.
- **Partially supersedes**, in the clauses §8's first table names: ADR-0073 and ADR-0338.

## Context

**What ADR-0338 needs.** A pin, and a style mark, is a pointer to a memory. ADR-0338 needs
to read that memory after it has been retired, in three places:

- **§4:8.** A pin on a memory that is ended or wrong, and names a successor, shows the
  successor. It follows the chain to a current memory, and the pin is not rewritten. §5:3
  says the same of a style mark, and §9:10 of a retirement written while a pin was being
  made.
- **§9:6.** Each observer run adds a `pinned` support for every pin "whose memory the store
  holds", whether or not the memory has been retired. The write is conditional on the
  revision read, and §9:10 adds the support "to the retired memory".
- **§4:8 and §8:1.** The panel shows a pin whose chain reaches no current memory as no longer
  current.

**What `MemoryStore` serves today.**

- `get` and `get_many` omit any record that is not live at now (ADR-0045 §6, ADR-0086 §6).
- `search` returns only live records. `list_beliefs` says that a retired record "stays
  reachable through `export` alone", and that there is "deliberately no `include_retired`
  axis" (ADR-0073 §3).
- An end, a mark wrong or a replace closes the memory's validity (ADR-0328 §3:4, §5:10). An
  end dated after its own instant is refused, so a retired memory is never live at now.
- So no read by id returns a retired memory, or the successor it names. `export` does, but
  it returns the whole store, so its cost grows with everything Aether has ever kept.
  Calling it on every activation is not an answer.

**What already works.** The write path is not the gap. `MemoryWriter.apply` takes the
memory as the caller read it, and writes `IF_UNCHANGED` at that revision. `write_atomic`
judges presence physically: "an expired or window-closed row satisfies the presence
requirement". Nothing in ADR-0328 §5 refuses an add support on an ended or wrong memory. A
caller that can read a retired memory can therefore already add a support to it. Only the
read is missing.

**What lane 1 does meanwhile.** It follows a chain only as far as `get_many` returns
records, so a pin on a retired memory is shown nowhere (#3308).

**ADR-0073 §3's shape.** That decision kept inspection live-only, and called history "a
different surface". It deferred a rendered history view for want of a link from a retired
record to what replaced it. ADR-0328 §5:6 has since made that link: each retired memory and
its successor name each other.

## Decision

We will add one read to `MemoryStore`. It returns, by id, each memory the store holds,
whatever its status, and it does nothing else. Every read that answers what Aether holds
now stays live-only. A caller presents a memory as current only where a live read returned
it, and follows a successor itself, hop by hop.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the authorization to
> ratify stands. An assigned number or a green review alone does not change its status.

> **Normative.** No lane implements this decision before it merges `Accepted` (golden rule
> 5, ADR-0015 §5).

> **Normative.** §2 to §4 are implemented in one lane, the `MemoryStore` triad of ADR-0137
> §2: the `Protocol` member, the conformance suite's cases, the canonical fake, and
> `SqliteMemoryStore` as the primary production implementation, with every other
> implementation of `MemoryStore` in the package.

### 2. The history read

> **Normative.** `MemoryStore` gains one member, the **history read**. It takes a sequence
> of ids and returns, keyed by id, the memory the store holds at each, whether its status is
> `current`, `ended` or `wrong`. Its exact name and signature are the triad lane's, within §2
> to §4.

> **Normative.** The history read returns each memory whole, as stored: its status, its
> validity, its operations log, with the successor any operation names, its supports and its
> revision.

> **Normative.** One call to the history read is one snapshot. Every id in it is judged
> against one instant and one state of the store, as `get_many`'s are (ADR-0086 §6).

> **Normative.** The history read answers in `get_many`'s shape (ADR-0086 §6): an empty
> sequence returns an empty mapping with no round trip, duplicate ids collapse, and the
> argument has no size cap.

> **Normative.** The history read raises `MemoryStoreError` where the store cannot be read
> or a stored record is corrupt, as `get_many` does.

**Why one member, and a batch.** Every caller resolves several ids at once: the block
resolves all of a person's pins and marks, and the observer's pass resolves every pin
lacking a support. A batch makes one call per hop of the walk, whatever the number of pins.
A single-id form would be a second spelling of a one-element batch.

**Why whole records.** The observer needs the retired memory's supports, to see whether a
`pinned` support is already there, and its revision, to write conditionally (ADR-0328 §5:4,
ADR-0219 §2). The block needs the operations log, to find the successor. The panel needs the
wording. A read returning only successor ids would serve the block alone.

### 3. What it answers for each id

| The id names | The history read |
| --- | --- |
| A memory, current, ended or wrong, its window open or closed | Returns it |
| A memory past its `expires_at` | Omits it |
| A memory that has been forgotten (deleted) | Omits it, because the store no longer holds it |
| An episode | Omits it |
| Nothing the store holds | Omits it |

> **Normative.** For every id, the history read returns the memory that `export` would carry
> at that id at the read's instant. It omits the id exactly where `export` would carry no
> memory at it.

> **Normative.** An id the history read omits is missing from the mapping. It is never an
> error, and never a `None` value.

> **Normative.** Where `get` would return a memory at the history read's instant, the
> history read returns the same record.

**Why an expired memory is omitted.** Retention wins over history. ADR-0045 §6 keeps an
expired record out of `export` because "a record the system promised to forget must not
resurface", and the history read is answerable to the same promise. It follows that a
memory is never more reachable through the history read than through `export`.

**Why a forgotten memory is omitted.** It is erased, so there is nothing to return.
Forgetting it also removes every pin and mark on it (ADR-0338 §4:9).

**Why an episode is omitted.** An episode has no status and names no successor, and no
caller here holds an episode id. `get_many` already answers for episodes. A second door to
them would have to restate the rules for open episodes (ADR-0286 §6), for no reader.

**Why an unknown id is omitted, not refused.** This is `get_many`'s answer, for its reason:
the caller's question is which ids resolved. A pin whose memory was forgotten after the
pin's removal is a normal case, not a fault.

### 4. What it is not

> **Normative.** The history read takes ids alone. It never searches, ranks, lists,
> enumerates or pages.

> **Normative.** The history read follows no chain. It returns the memory at each id it is
> given, and a successor only where its id is given too.

> **Normative.** `get`, `get_many`, `search` and `list_beliefs` stay live-only, as ADR-0045
> §6 and ADR-0073 §3 rule. None of them gains a parameter, a mode or a default that reaches a
> memory that is not live.

> **Normative.** The history read says nothing about liveness. Whether a memory is current
> is answered by a live read alone (§5:1).

**Why the store does not follow chains.** ADR-0328 §11:1 keeps `MemoryStore` mechanical: it
returns memories whole and computes nothing beyond §7's derivations. Following a chain is a
reading of ADR-0328 §5's log, with rules of its own: which successor to take, and where to
stop (§5:2, §5:3). The callers also want different things:

- the block wants the chain's current end;
- the observer's pass wants the pinned memory itself, since a pin adds no support to a
  successor (ADR-0338 §4:8);
- the panel wants both.

A store that followed chains would serve one of the three, and make the other two ask for
less than they are given. Chains are short, because each hop is a retirement that named a
successor, so a walk costs a call or two per hop.

**Why ADR-0073 §3 still holds.** "What do you believe about me" is still answered only by
reads that return live memories. The history read is the different surface §3 named. It is
reached by id, from a pointer the caller already holds, and never by browsing.

### 5. The callers, and what binds them

> **Normative.** A caller of the history read presents a memory as current only where a live
> read (`get`, `get_many`, `search` or `list_beliefs`) returned it. A memory that only the
> history read returned is shown, where it is shown at all, as no longer current.

> **Normative.** A caller following a pin or a style mark to a successor (ADR-0338 §4:8,
> §5:3) takes, at each memory along the chain, the successor named by the latest operation
> in that memory's log that names one.

> **Normative.** That walk starts at the pin's or the mark's own memory, and ends at the
> first memory along the chain that a live read returns, which is the chain's **current
> end**. Otherwise it ends at a memory that names no
> successor, at an id the history read omits, or at an id the walk has already read, and in
> each of these three cases the chain reaches no current memory.

> **Normative.** Where ADR-0338 says that the memory store holds a memory (§4:9, §7:10,
> §9:6), the store holds it exactly where the history read returns it.

> **Normative.** The person block shows, for a pin or a style mark, its chain's current end
> alone, and nothing of any other memory along the chain.

> **Normative.** The observer's pin pass (ADR-0338 §9:6), and its retirement guard (§9:9,
> §9:10), read each pin's memory through the history read. Each adds the `pinned` support to
> the memory that read returned, whatever its status, conditionally on the revision it
> returned.

| Caller | What it reads through the history read |
| --- | --- |
| The person block (ADR-0338 §4:8, §5:3, §6:3, §7:10) | A pinned or marked memory that a live read omits, and each successor along its chain. Also the check before each planning round that the block's memories are still held |
| The observer's pin pass and retirement guard (ADR-0338 §9:6, §9:9, §9:10) | The pin's own memory, for its supports and revision |
| The panels (ADR-0338 §4:8, §8:1) | The pins no longer current, and the memories their chains pass through |

**Why the latest successor.** A memory can be retired twice: an ended memory may later be
marked wrong (ADR-0328 §5:7), and each operation may name a successor. The later operation
is the later finding about what replaced the memory, so it governs.

**Why the walk is sound across calls.** A successor is created in the same write that names
it (ADR-0328 §5:6). Any successor a read reveals was therefore held in that read's state,
and is missing from a later read only where it has been forgotten since. Each hop reads a
state no older than the hop before it. A cycle cannot arise from §5:6, because each
successor is created after the memory that names it, so the stop at an id already read
guards only against a corrupt store.

**Why a live read decides "current".** Liveness stays judged by one predicate, the store's
(ADR-0045 §6, ADR-0072 §7). A caller never computes currency from a status field and a
clock of its own. The history read finds the candidates, and a live read confirms the end.

### 6. Delivery and order

> **Normative.** The triad lane (§1:3) merges before ADR-0338's lanes 5 and 6, the observer
> and the panels, are briefed. Each of those lanes reads through the history read in its own
> lane, as §5 requires.

> **Normative.** Moving ADR-0338's person block onto the history read (§5:1 to §5:5) is a
> lane of its own, in `orchestration/`, briefed after both the triad lane and ADR-0338's lane
> 1 have merged. Where the triad lane merges before lane 1's first review, the dispatcher may
> instead fold the move into lane 1.

> **Normative.** The person model does not go live on a person's hub (ADR-0338 §11:2) before
> the triad lane and the lane of §6:2 have merged.

**Why the block's move is a lane of its own.** Lane 1 ships the block against `get_many`
alone, and ships the conservative reading of #3308: a pin on a retired memory is shown
nowhere. That is a safe interim, since it never shows a retired memory as current. Moving
the block onto the history read touches `orchestration/` alone. It consumes the contract, so
it cannot ride in the triad lane (ADR-0137 §4), and it changes the block, so it follows lane
1. It is small: one walk and one check. Lane 1 can carry it only where the contract merges
before lane 1 is reviewed, which is the fold §6:2 leaves to the dispatcher.

### 7. What this decision does not decide

| Not decided here | Why it waits |
| --- | --- |
| A rendered history view, "what did you used to believe", for retired memories in general | ADR-0073 §3 left it to a decision of its own. The history read reaches a memory only by id, and the only caller rendering a retired memory is ADR-0338's panel, for pins no longer current |
| A read of memories as they stood at a past instant | The as-of read ADR-0045 §1 deferred. The history read returns each memory as it is stored now |
| A history read of episodes | No caller needs one (§3) |

> **Normative.** Each item the table names takes a decision of its own before any lane
> builds it.

### 8. Relationship to earlier decisions

Superseded in part. Every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0073 | §3's and §10's deferral of a history surface, for the store's read alone: a retired memory is reachable by id through the history read as well as through `export`. The inspection read stays live-only, and the rendered history view stays deferred | §2:1, §4:3, §7 |
| ADR-0338 | §11:1, in the addition alone: the triad lane comes before lanes 5 and 6 are briefed, and the block's move is a lane of its own; §11:2, in the addition alone: going live also waits on those two lanes | §6:1 to §6:3 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0045 §6 | Nothing: `get` and `search` hide closed windows, `export` keeps them, and retention wins over history in the history read as it does in `export` (§3:1). Its "No new *method* is added to the Protocol" described that decision's own change |
| ADR-0086 §6 | Nothing: `get_many` never disagrees with `get`. The history read makes no claim about liveness (§4:4), and agrees with `get` on every memory `get` returns (§3:3) |
| ADR-0328 §11:1, §11:2 | Nothing: the store stays mechanical, follows no chain (§4:2), and a memory is live exactly as before |
| ADR-0328 §5:4, §5:6 | Nothing: a retired memory is written conditionally on the revision the history read returned, and the successor link is the one §5:6 writes |
| ADR-0338 §4:8, §4:9, §5:3, §7:10, §9:6, §9:9, §9:10 | Nothing: "the store holds" reads as the history read returning the memory (§5:4), and pins and marks follow their successors as written |
| ADR-0338 §10:1 | Nothing: it puts the person-model store outside `MemoryStore`'s contract, and says nothing of `MemoryStore`'s reads |
| ADR-0007 §3 | Nothing: `export` stays the data-rights surface, and its contents are unchanged |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0073 and ADR-0338, atomically with this ADR under ADR-0070 and
> ADR-0082, preserving their ratified bodies. The replacements take effect on this ADR's
> ratification.

## Consequences

**What becomes possible.**

- A pin follows its memory's successors, as ADR-0338 §4:8 says, without the pin being
  rewritten and without a copy of anything in the person-model store.
- The observer's pin pass reaches a retired memory, and so earns the confirmation a pin made
  before a retirement (ADR-0338 §9:10).
- The panel can say which pins are no longer current, and why.
- Each of those reads costs a call per hop, never a read of the whole store.

**What it costs.**

- **One member on `MemoryStore`.** Every implementation carries it: `SqliteMemoryStore`,
  `InMemoryMemoryStore` and the canonical fake. The conformance suite gains its cases. That is
  the triad lane (§1:3). On the SQLite store it is `get_many`'s read with the expiry filter
  kept, the validity filter dropped and episodes left out.
- **Docstrings that go stale.** `list_beliefs` says that a retired record is reachable
  "through `export` alone", and the class docstring says that reads "come in three shapes".
  The triad lane restates both.
- **Two lanes before going live** (§6:3): the triad and the block's move.
- **A walk is several snapshots, not one.** Each hop is consistent in itself, and §5's
  "Why the walk is sound" says why the sequence is too.
- **Records.** Header records on ADR-0073 and ADR-0338.

**What would reopen it.**

- A caller that wants to list retired memories rather than resolve one. That is ADR-0073's
  history view, and a decision of its own (§7).
- Chains long enough that a call per hop costs something real.
- A caller that needs a retired episode, or a memory as it stood at a past instant.

## Alternatives considered

- **`export()` on each activation.** Rejected: its cost grows with the whole store, and it
  returns every record to find a few.
- **An `include_retired` parameter on `get` or `get_many`.** Rejected: it is the flag
  ADR-0073 §3 refused. Every live caller's read would then be a call that has to pass the
  flag correctly, and a wrong default presents a retired memory as current.
- **A read that follows the chain and returns the current end.** Rejected (§4): the observer
  needs the pinned memory itself, and the panel needs both. It would also put ADR-0328 §5's
  reading into the store, against §11:1.
- **A read returning only successor ids.** Rejected: the observer needs the retired memory's
  supports and revision, and the panel its wording.
- **The person-model store copying the successor when a memory retires.** Rejected: ADR-0338
  §10:3 keeps that store free of copies, §4:8 says the pin is not rewritten, and the memory
  writer would have to write a second store in its own write.
- **The block resting on `get_many` alone**, as lane 1 ships it. Kept as the interim and
  rejected as the end state: a pin on a retired memory would vanish, against ADR-0338 §4:8.
- **Answering episodes too.** Rejected (§3): an episode has no status and no successor, and
  nothing here asks for one.
