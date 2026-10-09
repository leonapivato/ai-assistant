# 301. A story label may name an earlier episode the channel window shows

- Status: Partially superseded by ADR-0303 (§1:2's and §1:3's label defect, for an item that links to no activation; §1:3's list, for a transcript message the reader's bookkeeping records; §1:4, in the addition alone; §1:6, whole)
- Date: 2026-10-08
- Scope: [M42](https://github.com/leonapivato/ai-assistant/milestone/9), [#2753](https://github.com/leonapivato/ai-assistant/issues/2753): which labels understanding's story links may cite.
- Dependency: ADR-0300, whose §6 [#2752](https://github.com/leonapivato/ai-assistant/pull/2752) implemented; ADR-0276 and ADR-0282, implemented.
- Authorization: lane L2, building ADR-0300 §6 in #2752, found that the clauses as written leave a conversation's own earlier turns unlinkable and filed #2753 for a ruling. On 2026-10-08 the dispatcher ruled that an `H` label naming a channel item that is a stored activation episode resolves as a `P` label naming that episode would, left the conditions to this ADR, and assigned 0301. That authorizes drafting and numbering, not ratification or implementation.
- Partially superseded: 2026-10-08 by ADR-0303 — four scopes. A story label naming a
  place-window item that links to no activation is dropped and counted in
  `grounding_dropped` and is no label defect, so it takes no part in the repair
  (§1:2, §1:3). A transcript message the chat reader's bookkeeping records as taken in
  resolves to that activation (§1:3's list). The resolution also reads the link
  records the window brings with it (§1:4, in the addition alone). The instruction
  lets a story label name any place-window item not marked not linkable (§1:6). §1:1
  stands as the record a tail record or a one-exchange item links by, and so does
  every other clause. These scoped replacements take effect on ratification of
  ADR-0303. This reciprocal header record accompanies the numbered draft under
  ADR-0070 and ADR-0082; the ratified body below is preserved.
- **Decides no `core` surface.** No Protocol, type, field, enum member or validator changes: `story_labels` and `story_links` keep the shapes ADR-0300 §6:6–§6:7 give them, and only which labels resolve changes.
- **Partially supersedes** [ADR-0300](0300-a-story-keeps-a-page-of-notes-and-where-its-matter-stands-is-worked-out-from-records.md) — **two scopes.** **§6:7's resolution, in the addition alone**: an `H` label naming a channel-window item that is a stored episode the pass admitted also resolves, to that episode's activation as an activation member (§1 below). **§6:8's *"or to a channel item"*, for those items alone**: such a label is not a label defect; an `H` label naming any other channel item still is. Every other clause stands, §6:1's candidates, §6:6's field, §6:9's instruction and §6:12's links included.

## Context

ADR-0300 §6:7 resolves the labels of `story_labels`: *"an `S` label resolves to its
story as a story member, and a `P` or `M` label naming an episode resolves to that
episode's activation as an activation member"*. ADR-0300 §6:8 makes *"A story label
that resolves to nothing, or to a channel item or a semantic record"* a label defect,
repaired once and then dropped and counted. ADR-0276 §3:5, *the same exchange in both
windows*, renders an episode of the episode window whose stored id equals a channel
item's identifier *"once, as the channel item under its `H` label … it takes no `P`
label"*.

Read together, an earlier episode that reaches the understanding call **only** under
an `H` label can never be linked. At `origin/main` the channel window takes three
shapes (`orchestration/understanding.py`, `ChannelWindow`), and the gap is in two of
them:

- **The conversation's tail** (`ConversationWindow`, ADR-0276 §3:1). It is the window
  of `converse_spoken`, which ADR-0293's partial supersession of ADR-0276 §3:1–§3:2
  leaves on the tail, and of `converse`, which ADR-0293 §11:2 replaces for the
  conversation but which is still on the engine surface and reaches the CLI and the
  browser (ADR-0299 §3:1). Every item of it is a stored episode of this conversation,
  admitted by ADR-0276 §4:9's predicate before it is rendered. Where the selector
  reaches one, it is one exchange and takes no `P` label; recall keeps no record whose
  id is a channel item's (ADR-0282 §4:1), so it takes no `M` label either; and a
  spoken turn takes no episode window at all (ADR-0276 §4:13), so on that path every
  earlier episode the pass sees is an `H` item. On these paths a conversation's own
  earlier turns, the likeliest earlier episodes of the same matter, cannot be linked,
  and ADR-0300 §6's closing sentence, *"So 'my running' becomes a story the second
  time it comes up"*, fails across two turns of one conversation unless both already
  sit in a story.
- **A supplied window** (`SuppliedWindow`), where an item's `item_id` equals the id of
  an episode the selector returned: one exchange under ADR-0276 §3:5, so the same.

The third shape does **not** have the gap. The chat's reader brings in the
conversation's recent transcript as the window (ADR-0293 §6:4), and a transcript
message is not a stored record: it carries no identifier an episode shares
(`TranscriptWindow`), so ADR-0276 §3:5 never applies to it. The conversation's earlier
episodes reach that call as `P` items of the episode window, where the selector's
recency bound reaches them, or as `M` items of recall, and ADR-0300 §6:7 already links
them. #2753 states the gap *"on the conversation channel"*; as built, it holds on the
tail and supplied paths, not on the chat reader's.

## Decision

We will let a story label cite an earlier episode under whichever label the pass
rendered it, as long as the pass admitted that episode, and we will change nothing a
record or the wire carries. Every clause below stands alongside ADR-0300, ADR-0276 and
ADR-0282 except where this decision's header names a scope it replaces.

### 1. An `H` label naming an admitted stored episode resolves to its activation

> **Normative.** In `story_labels`, an `H` label resolves to an activation member where
> the channel-window item it names is a stored episode the pass admitted: a record of
> the conversation tail ADR-0276 §3:1 renders, admitted by ADR-0276 §4:9's predicate,
> or an item that is one exchange under ADR-0276 §3:5 with an episode of the episode
> window, admitted under ADR-0282 §2:6–§2:8. It resolves to that episode's activation
> exactly as a `P` label naming that episode resolves under ADR-0300 §6:7.

> **Normative.** An `H` label naming such an episode where the episode records no
> activation resolves to nothing as a story label, as a `P` label naming that episode
> does, and is a label defect under ADR-0300 §6:8.

> **Normative.** An `H` label naming any other channel item resolves to nothing as a
> story label and remains a label defect under ADR-0300 §6:8: a transcript message, a
> supplied item that is not one exchange, and a supplied item whose `item_id` equals
> the id of a stored episode the episode window does not hold.

> **Normative.** The resolution reads only the records the pass already holds to
> render the two windows. It fetches no record and reads no store to decide whether an
> item is a stored episode, so no episode the pass did not admit becomes linkable.

> **Normative.** Outside `story_labels`, an `H` label resolves exactly as ADR-0276 §2
> and §3 have it, to a `channel_item` referent, and this decision changes no referent,
> no rendering of the channel window and no label of any sequence.

> **Normative.** The instruction states that a story label may cite an `H` label whose
> item the rendering marks as an earlier recorded exchange or as also present in the
> episode window, and no other `H` label; and the code-owned statement of a repair
> completion names a story label citing any other `H` label as a defect.

**Why a stored episode the pass admitted, and not only one exchange.** One exchange
is the narrower test, but it adds no protection the admission rule does not already
give, and it leaves the gap where it is widest. A tail record beyond the selector's
reach, and every tail record of a spoken turn, which takes no episode window, is a
stored episode that ADR-0276 §4:9's predicate admitted and the model was shown; only
the one-exchange test would keep it unlinkable. On a turn of unbounded audience that
predicate withholds every `OWNER`-placed record from the tail, and *"A withheld record
reaches no rendering, no label, no referent and no version"*, so it takes no `H`
label to cite.

**Why not any item whose identifier is a stored episode's id.** A supplied item's
identifier is the channel's own: *"A supplied channel item is not a record"* (ADR-0276
§4:10), and it establishes nothing (ADR-0274 §5's fourth clause, which ADR-0276 §3:6
keeps). Resolving it by id alone would link an episode the pass neither fetched nor
admitted, chosen by a value the channel supplied. Where its id matches an episode the
window does hold, that episode was admitted under ADR-0282 §2:8 and is the one
exchange the first clause above already covers.

The story-links stage needs no change. ADR-0300 §6:12 links the activation *"into
every story a linked earlier episode belongs to by then"* and starts a story from
*"the earlier episodes that belong to no story by then"*; an activation member
resolved from an `H` label is a linked earlier episode on the same terms as one
resolved from a `P` label.

### 2. The wire and the episode record

> **Normative.** This decision changes no shape the wire carries and no shape of
> `EpisodicMemory.processing_record`: `story_links` holds the same `StoryMember`
> values, built by the same rule. Its implementation advances no `PROTOCOL_VERSION`,
> changes no `schema_version` and does not advance the episode-record format marker.

> **Normative.** An understanding recorded before the implementation lands keeps the
> links it recorded, and no later activation rewrites them, on ADR-0276 §7:3's last
> clause, which stands.

Nothing of ADR-0300 is live on a hub until the phases' cutover (ADR-0300 §13), so no
such record exists outside a test hub.

### 3. Delivery

This section is guidance for the lanes, except where marked.

> **Normative.** No implementation implements this decision until this numbered ADR
> has merged `Accepted` under ADR-0015 §5.

One lane, **`orchestration`**, on #2752's resolution of story labels: §1's resolution in the
understanding stage, the instruction's and the repair statement's text, and tests
that a tail record and a one-exchange item each link their activation through an `H`
label, that a withheld tail record takes no label, and that a transcript message's
`H` label and a non-matching supplied item's are dropped and counted after the one
repair. It touches no other subsystem.

### 4. Relationship to earlier decisions

| Earlier decision | What changes |
| --- | --- |
| ADR-0300 §6:7, §6:8 | As this ADR's header states |
| ADR-0300 §6:1, §6:6, §6:9, §6:12, §12 | Nothing: the candidates, the field, the instruction's three statements, the links' writing and the wire stand, and §1 adds one statement to the instruction beside §6:9's |
| ADR-0276 §3:3, §3:5, §4:9, §4:10, §4:13 | Nothing: one exchange is still rendered once under its `H` label with one referent, no label survives the call, and what is admitted, withheld or not a record is decided there |
| ADR-0282 §2:6–§2:8, §4:1 | Nothing: they decide which episodes the pass admits and what recall searches past |
| ADR-0293 §6:4, §11:2 | Nothing: when `converse` leaves the surface the tail path narrows to `converse_spoken`, and §1 still reads it |

> **Normative.** This numbered draft records its replacements on ADR-0300's status
> line and in a dated header note of ADR-0300, atomically with this ADR under ADR-0070
> and ADR-0082, preserving its ratified body. The replacements take effect on this
> ADR's ratification.

## Consequences

**What becomes possible.** On the tail and supplied paths, a follow-up to the turn
before it can be linked as one matter, so a second mention starts a story as ADR-0300
§6 intended, whether the earlier turn reached the call as one exchange, as a tail
record beyond the selector's reach, or on a spoken turn.

**What it costs.** One more resolution rule in the understanding stage, and one more
sentence in its instruction. Nothing changes on the wire or in a record.

**What stays open.**

- **The stories of a tail record outside the episode window are not candidates.**
  ADR-0300 §6:1 reads the stories of the episode window's episodes and of recall's,
  so a story only an older tail record or a spoken turn's tail belongs to is not
  shown to the model. §6:12 still links the activation into it once the record is
  linked. If the test hub shows that mattering, it is a change to §6:1.
- **On the chat reader's path, the transcript and the episode window show the same
  turn twice**, as an `H` message and a `P` episode, and only the `P` label may be
  cited. If the test hub shows the model citing the message, the repair statement is
  where it is caught; linking a message to the episode of the activation that took it
  in would need the reader's bookkeeping (ADR-0293 §6) in the understanding phase, and
  a decision of its own.

## Alternatives considered

- **One exchange only.** Narrower, and no safer: it leaves every spoken turn's tail
  and every tail record beyond the selector's reach unlinkable, though each was
  admitted and shown (§1).
- **Any channel item whose identifier is a stored activation episode's id.** It would
  resolve a supplied item by an identifier the channel chose to an episode the pass
  never admitted (§1).
- **Give a one-exchange episode its `P` label as well.** It changes ADR-0276 §3:5,
  which renders the exchange once with one referent, to fix a rule of ADR-0300's.
- **Leave §6:7–§6:8 as written.** The rule start then fails across two turns of one
  conversation on every path that renders the tail.
