# 386. A record's home joins the fields, the reads and the minting members earlier decisions closed

- Status: Proposed
- Date: 2026-11-26
- Scope: decision D4 of milestone 22, "Every record has a home" (acceptance
  [#3709](https://github.com/leonapivato/ai-assistant/issues/3709), batch
  [#3711](https://github.com/leonapivato/ai-assistant/issues/3711)). For the stores ADR-0383 §3
  gives a home other than the memory store, it adds the home to each earlier clause that closes a
  record's fields, what a read gives back of it, or what its minting member takes (§2 to §5); says
  how the home reaches each minted record and how each store refuses a home it may not write (§6);
  and records what this does to ADR-0383 §12 (§7).
- Authorization: the owner's words, verbatim. On 2026-11-26, "Yes, agreed", to "Do you agree this
  scope: "Yes, agreed" or "Change something"?", the scope being what #3709 records. The owner ruled
  nothing about fields, members or supersessions: every rule below is this decision's. The
  coordinator assigned 0386 and ratifies it, under the owner's delegation, once its reviews are
  green.
- **Contract-surface decision; a decision only.** It changes no Protocol, type or code. It decides
  `core` fields and the arguments of `StoryStore`, `NotificationStore` and `ConversationStore`
  members, so it takes the adversarial and the architecture review. Building it is a breaking change
  under golden rule 5, in the build lanes ADR-0383 already scopes.
- **Partially supersedes**, as §8 records, each in the addition alone save the last:
  [ADR-0289](0289-a-story-store-holds-which-experiences-belong-to-the-same-matter.md) (§2:1, §3:1,
  §3:10, §3:14);
  [ADR-0215](0215-a-dismissed-notification-keeps-suppressing-its-own-key-until-the-fact-it-named-perishes.md)
  (§7:1's *no field*);
  [ADR-0074](0074-conversation-is-an-entity-and-every-turn-is-an-episode.md) (§1's and §9's
  accounts of what `Conversation` carries);
  [ADR-0293](0293-the-hubs-chat-is-a-hosted-medium-and-a-conversation-keeps-its-own-transcript.md)
  (§5:2); [ADR-0306](0306-a-capability-declares-what-its-calls-do-every-call-is-checked-by-rule-and-acting-claims-and-records-what-it-does.md)
  (§6:1's `ActivationEffect` row); and
  [ADR-0383](0383-each-record-carries-its-home-and-every-read-a-work-a-producer-or-a-run-makes-is-of-a-store-bound-to-one-sight-which-answers-as-though-it-held-only-what-that-sight-sees.md)
  (§12:2, in its reach).

## Context

ADR-0383 puts a required home on stories, held notifications, conversations and each message, and
plan effects and observations (§3's table, §3:1, §5:4), and says it supersedes nothing (§12:1) and
that every earlier clause on what a store holds or returns, or on the arguments of its members,
holds as written (§12:2). For stories both cannot hold: ADR-0289 §2:1 lists what a story carries,
and ADR-0300's record of its partial supersession keeps the header at "what §2:1 lists and nothing
more"; §3:14 lists what the header read gives; §3:1 lists what `create` takes. The story build lane
stopped there. This decision makes the least change that lets ADR-0383 §3:1 and §5:4 be built, and
asks the same question of the other three stores.

How the sweep was made, at `4e7a31040`: the ADR corpus was searched for each record's type and
minting member by name and for closing words ("exactly", "nothing else", "nothing more", "no
field", "no other"), and the marked clauses of every ADR each type's docstring cites were read. It
is not claimed to be exhaustive.

## Decision

### 1. Status and scope

> **Normative.** No lane implements against this decision before it merges `Accepted` (golden
> rule 5, ADR-0015 §5).

> **Normative.** This decision adds a home where an earlier clause closes a record, a read or a
> member, and changes nothing else those clauses say.

> **Normative.** This decision does not decide `PROTOCOL_VERSION`; ADR-0124 §9:2 rules it.

### 2. Stories

> **Normative.** A story also carries its home (ADR-0289 §2:1, in the addition alone), and the
> header every read gives back also gives it (§3:14, in the addition alone).

> **Normative.** `create` also takes, as a required input with no default, the home the story it
> mints lands in, and writes it on that story (ADR-0289 §3:1, in the addition alone).

> **Normative.** The story a split mints takes the home of the story it is split from, and the
> split gains no argument for it (ADR-0289 §3:10, in the addition alone).

A home is not the "owner" §2:1 rules out, and that word stands: ADR-0289's context reads the list
as what a story holds of its matter ("no text, no state and no authority"), while a home says which
domain the record lies in (ADR-0383 §2:1). ADR-0300's "nothing more" is its header's reading of
§2:1, not a marked clause of ADR-0300 (ADR-0089 §3), so it follows §2:1 and ADR-0300 needs no
record. A merge mints no story, and each story keeps its home (ADR-0383 §4:6).

### 3. Held notifications

> **Normative.** `HeldNotification` also carries its home (ADR-0215 §7:1's *no field*, in the
> addition alone).

> **Normative.** `NotificationStore.admit` also takes, as a required input with no default beside
> the candidate, the home of the record it may write; `NotificationCandidate` gains no home.

The candidate stays as ADR-0130 §3:1 offers it, and the outbox, which ADR-0383 §3 gives no home,
holds candidates; the `NotificationWriter` the producer offers through supplies the home to
`admit`, by ADR-0383 §4. ADR-0215 §7:1 can be read as bounding only its own change; superseding it
in the addition leaves no reading under which the home contradicts it.

### 4. Conversations and messages

> **Normative.** A `Conversation` also carries its home (ADR-0074 §1's and §9's accounts of what
> it carries, in the addition alone), and `ConversationStore.start` takes, as a required input with
> no default, the home of the conversation it mints.

> **Normative.** Every transcript entry also carries its home (ADR-0293 §5:2, in the addition
> alone), and the message a write hands `append_message` carries it as a required field of
> `NewMessage`; `append_message` gains no argument.

No clause found closes `append_message`'s arguments or what `start` takes.

### 5. Plan effects and observations

> **Normative.** An `ActivationEffect` also carries its home (ADR-0306 §6:1's `ActivationEffect`
> row, in the addition alone), as a required field of the record every member that writes one takes
> whole; no member gains an argument.

> **Normative.** An `ObservationRecord` carries its home as a required field of the record
> `write_observation` takes whole; `write_observation` gains no argument.

ADR-0329 §16:1 lists what an observation record holds and leaves "exact shapes" to its lane, and
ADR-0346 §4:6 added to it without a supersession, so no clause closes it and none is superseded.

### 6. A home a store may not write

> **Normative.** Every home §§2–5 name is set by code by ADR-0383 §4, and never a model's value
> (ADR-0383 §4:6).

> **Normative.** A store asked to mint or write a record whose home `home_may_be_written` does not
> allow writes nothing and raises, as the row below states for it (ADR-0383 §4:7's last item).

| Store | Its refusal |
| --- | --- |
| Stories | `ValueError` before any check or write, a malformed argument as ADR-0302 §4:3 has one; not a refusal outcome of ADR-0289 §3:15, and not `StoryStoreError`, which is a file fault |
| Notifications | `ValueError` before the atomic act of ADR-0130 §3:2, so no record and no unit of budget; not a `DROP`, which names a §5 condition, and not `NotificationStoreError`, a store fault |
| Conversations | `ValueError` before any I/O, from `start` and `append_message`, in ADR-0283 §6:3's shape |
| Plans | `PlanningError`, writing nothing, from every member that writes an effect or an observation, as ADR-0306 §6:2 refuses a claim |

### 7. ADR-0383

> **Normative.** ADR-0383 §12:2 does not reach the clauses this decision supersedes in part: each
> holds as this decision leaves it.

§12:1 stays true of ADR-0383: the supersession is this decision's. Every other clause of ADR-0383,
§13 and the `Amended:` note on its header included, stands.

### 8. Relationship to earlier decisions

The clauses the header names are superseded in part as §§2–5 and §7 state, and each carries a
header record. ADR-0300's header, ADR-0130, ADR-0283 §6:1, ADR-0329 §16:1, ADR-0346 §4:6 and
ADR-0350 §12:9 stand: none closes what this adds.

## Consequences

The build lanes for stories, conversations and plan records build against ADR-0383 with no clause
left closed, each knowing the input its minting member takes and the error it raises.

## Alternatives considered

- **Every closing clause read as open, on ADR-0302's `answers` precedent.** It reaches a keyword on
  `create`, not the header's "nothing more" or ADR-0293 §5:2's "exactly".
- **The home on `NotificationCandidate`.** It would put a home on what the outbox holds, which
  ADR-0383 §3 gives none.
- **A typed refusal outcome for the story store.** It adds a `StoryRefusalReason` member and a place
  in the fixed check order for a write ADR-0383 §2:3 refuses whatever the stories hold.
