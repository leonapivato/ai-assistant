# The episode store is the one record

**The question.** Where does the record of what happened live, so that the same
event is not held in several stores that must be kept in step, and forgetting
something means one delete?

**The answer proposed.** The episode store is the one record. An episode is
kept until the user forgets it; nothing expires it by default. Every other
store holds episode ids, never copies of what an episode says. A channel's
history, a conversation's history and the user's read-back of past exchanges
are views over the episodes, found by index. The transcript archive is retired,
because the episodes it duplicated are now kept. Forgetting an episode is one
delete in the memory store, which also removes the episode from the beliefs
derived from it and deletes those it was the last support for. `model_eligible`
is retired, and the episode's end entry is the same on every channel. An episode is an append-only log with an end entry, open while its
activation runs, so what a crash leaves behind is an episode without an end.

This absorbs the decisions of ADR-0283 (PR #2614, accepted but not merged),
which is closed in favour of this proposal: most of ADR-0283's machinery was
there to keep three stores in step, and this removes two of them.

## Baseline

Wiki, read at `ea98b15`:

- [Episodes](https://github.com/leonapivato/ai-assistant/wiki/Episodes): an
  episode is "written once … never changed", and, as direction, "A log, read
  through current views".
- [Channels](https://github.com/leonapivato/ai-assistant/wiki/Channels): the
  channel is the medium; a conversation is one kind of channel.
- [Channel window](https://github.com/leonapivato/ai-assistant/wiki/Channel-window),
  [Episode window](https://github.com/leonapivato/ai-assistant/wiki/Episode-window),
  [Recall](https://github.com/leonapivato/ai-assistant/wiki/Recall),
  [Stories](https://github.com/leonapivato/ai-assistant/wiki/Stories).

ADRs, at `5d872812`:

- ADR-0007: the data-rights surface (view, export, delete) and retention
  enforced at the store.
- ADR-0074: a conversation is an entity and every turn is an episode. §3 (the
  episode's id), §7 (the episode horizon, `episode_retention`, and conversation
  reclaim), §8 (deletion, index first), §9 (the `ConversationStore` and its
  turn index).
- ADR-0077: the observer proposes beliefs from episodes, reading turns after a
  watermark.
- ADR-0225: the transcript archive keeps the exchange as text, under its own
  retention, and only the user reads it.
- ADR-0275: an episode records one activation after processing ends. §3 (the
  capture unit), §8 (written once, when processing ends; the verification and
  compensation of §8:11), §9 (the conversation index fields).
- ADR-0276, ADR-0280, ADR-0281, ADR-0282: what the understanding, the
  controller's choices, recall and the phases write onto the episode, and the
  saved reads.

Issues: #2613 (one episode, open while the activation runs), #2608 (saved reads),
#2592 (`context_withheld`), #2528 (the observer is blocked), #2614 (ADR-0283, to
be closed unmerged).

## What is wrong today

One exchange on a conversation is recorded in three places, with no transaction
across them:

1. **The episode**, in the memory store, written once when processing ends.
2. **The turn row**, in the conversation store: the ordinal, eligibility, parked
   binding, delivery and observed marks. The conversation's history is read from
   these rows, and each names its episode.
3. **The archive entry**, in the transcript archive: the asked and replied text
   again, under a separate retention, so the user can read it back after the
   episode expires.

Because the three are written in sequence, every crash point between them and
every forget that lands between them needs a rule. ADR-0283 spent seven review
rounds on those rules, and rounds three to six each moved a write to fix one
invariant and broke another. The order of the writes was not the problem; there
being three writes was.

Four further causes sit under that one:

- **The turn index is a second copy of the truth.** It holds eligibility that the
  episode also holds, and history is read from it rather than from the episodes.
- **Episodes expire.** ADR-0074 §7 gives episodes a horizon (`episode_retention`,
  30 days), on the view that episodes are substrate the observer distils into
  beliefs. The archive exists because of that horizon. But the observer is blocked
  (#2528), and recall and stories read episodes long after thirty days.
- **Copies of episode text live outside the episode**, so forgetting an episode
  does not forget what it said. The inventory found:
  - `RecalledItem.excerpt` and `UnderstandingReferent.excerpt`, saved inside
    later episodes;
  - `TranscriptEntry.asked` and `.replied`, in the archive;
  - `ParkedRead.utterance`, in the permissions store's parked reads;
  - `GoalElement.span` and `GoalInterpretation.outcome_span`, verbatim substrings
    kept in the planning store;
  - `ActionPlan.rationale`, interleaved into the episode's own `content`.
- **Forgetting does not reach what was derived.** `forget(record_id)` deletes the
  archive entry and the episode's rows, and nothing else. A belief whose
  `provenance.evidence` cites the episode stays, and shows the loss only as an
  `Evidence(content=None)` tombstone when read.

## The change

### The episode is kept until it is forgotten

Episodes no longer expire by default. `episode_retention` becomes an optional
user setting, unset by default; where the user sets it, expiry deletes as forget
does, cascade included. It stops being stamped at admission: expiry is computed
from the episode's end, so an open episode never expires.

Two things borrow `episode_retention` today and are given their own settings:
the goal-authorization row horizon (`orchestration/authorizing.py`) and the
conversation reclaim of ADR-0074 §7.

### The transcript archive is retired

With episodes kept, the archive holds nothing the episode does not. It is
removed: its store, its retention, its writes in the activation writer, its
discards in forget and in conversation deletion, and its engine, wire and CLI
surface. The user's read-back moves onto the episodes: search, show a
conversation, show one exchange, and forget one exchange or one conversation are
episode reads and forgets, and the CLI `transcript` subcommands are replaced by
episode commands with the same reach. ADR-0225's rule that only the user reads
the archive gives no model new text: everything the archive held, the episode
already held. Who may read an episode is the channel's audience, as the
[Channels](https://github.com/leonapivato/ai-assistant/wiki/Channels) page
directs, not a flag on the episode.

### Everything else holds ids

No store other than the episode store holds text an episode holds. Each copy
above becomes a reference:

- recall's and understanding's excerpts are dropped from what is saved; the
  saved read holds the ids and the score (ADR-0282 already moved recall this
  way), and a view that wants the text resolves it;
- a parked read holds its episode's id instead of the utterance;
- a goal span becomes the episode's id and a character range, resolved when
  read;
- the plan's rationale moves out of `content` into its own part of the episode,
  so `content` is derived from the episode's parts when the episode ends.

The one keyed exception is the opt-in source-material store the owner directed
on 2026-09-01: raw audio and images kept beside the episode, keyed by its id,
and deleted with it.

### A channel's history is a view over the episodes

The conversation store keeps the conversation entity only: its id, when it
started, its last activity and its tombstone. The turn index goes. A channel's
history, a conversation's history and export are read from the episode store by
an index on the episode's channel and its admission order. The ordinal is the
episode's position in that order. The channel is written once, at admission,
and never changes.

The turn row's other duties move onto the episode:

- **eligibility** goes with `model_eligible` (below);
- **delivery** becomes an annotation on the episode, the one field written after
  the end entry, and never read by a model;
- **the observer's cursor** runs over episodes in admission order rather than
  over turn rows;
- **the parked binding** is found through an index on the episode's links, until
  stories (M40) give it a home. This removes the parked-resume path's dependence
  on stories.

### The episode is an append-only log

An episode is written open at admission, with its id `activation:<id>`, its
channel and its admission time. Each stage appends its part as it ends. The end
entry closes it: status, reason, end time and response. Nothing is rewritten,
and nothing but delivery is added after the end.

The end entry is the same on every channel. Two of today's conversational fields
leave it:

- **`response_kind`** goes. The response is the text the activation produced on
  its channel, or none; whether it was a reply or a summary follows from the
  channel's kind.
- **`disposition`** (`ExchangeDisposition`) goes. What became of each plan step
  or route is already in the execution stage's part of the episode; a view that
  wants one line for the exchange derives it from there.

The episode's `content`, today composed for the conversation, is derived from the
episode's parts when it ends, the same way on every channel.

### `model_eligible` is retired

`model_eligible` existed so that the model reads from before M36 kept seeing what
they saw (ADR-0275 §7); the owner ruled on 2026-09-27 that this compatibility is
no longer needed. It is removed from the episode, from the memory store's
`search` and `select` (`episode_model_eligible`), from the turn row along with
the turn index, and from the episode window's exemption in ADR-0276 §4. A read
that should skip an unfinished or failed episode reads the end entry's status,
which says so directly. The cutover's fresh data directory holds no pre-M36
episodes for the flag to protect.

A crash leaves an episode without an end entry. Before the hub admits its first
activation it appends one to each such episode: `interrupted`, reason
`hub_stopped`, no response. Nothing else needs repairing, because
there is no second store for the episode to disagree with. This replaces
ADR-0283's `EpisodeEnding` and its restart rules.

From ADR-0283, unchanged:

- open episodes are visible: the episode window and the channel window show
  other activations' open episodes and never the activation's own; recall skips
  open episodes;
- each stage's part is written through as the stage ends;
- the #2608 saved reads (`ActivationWindows`, `StageFetch`, `RecalledItem.score`,
  `SAVED_READ_IDS_MAX`, with `_elided` counts) and #2592's `context_withheld`.

### Forgetting is one delete

Forgetting an episode deletes, in one memory-store transaction, the episode and
every belief whose `provenance.evidence` cites it. Both live in the `records`
table and the `vec_records` index, so the transaction is a local one.

A belief citing several episodes is weakened rather than deleted: the forgotten
episode's citation is removed from its `provenance.evidence`, and the belief is
deleted when its last cited episode is forgotten. So a belief never outlives all
of the episodes it came from, and never rests on one the user forgot. A belief
whose confidence the forgotten episode raised keeps the confidence it has; it is
not recomputed. Parked reads, goal elements and source
material naming the episode are deleted by their own stores on the same forget,
and a reference that outlives its episode reads as gone, as ADR-0074 already
tolerates.

Forgetting an open episode leaves a tombstone. The writer's next append to a
tombstoned episode is refused, and the writer then deletes the episode and its
tombstone instead of ending it; the restart does the same for a tombstoned episode
a crash left open. So a forget never races a write.

Forgetting a conversation stamps it, then forgets its episodes, found by
channel. There is no index to enumerate first.

## Options considered

- **Keep three stores and fix the write order (ADR-0283 as accepted).** It
  converged, but only with a saved ending, a restart that reconciles three stores,
  and compensation on three failure paths. Every future writer inherits those
  rules.
- **Keep the archive, stop expiring episodes.** Removes the archive's reason to
  exist while keeping its cost: a second copy of the text to forget.
- **Give episodes their own store, apart from beliefs.** Cleaner separation, but
  the cascade to beliefs then crosses two stores with no transaction, the problem
  this proposal removes. Kept in the memory store.
- **Delete every belief citing the episode.** The simplest cascade, and the
  owner's first ruling (2026-09-30), before weakening was folded in: a belief
  confirmed by many episodes would vanish when any one was forgotten.
- **Beliefs survive their episodes, marked unsupported.** Kinder to the user
  model, but a forgotten fact would stay known.

## Cutover

The hub moves to a fresh data directory, as the M39 deploys did. No migration of
existing turn rows, archive entries or expiry stamps.

## ADRs it would touch

ADR-0007 (retention), ADR-0221 (`disposition`), ADR-0074 (§3, §7, §8, §9), ADR-0077 (the observer's
cursor), ADR-0225 (retired whole), ADR-0275 (§3, §7's eligibility, §8 and its §8:11
compensation, §9), and ADR-0276, ADR-0280, ADR-0281 and ADR-0282 where they save excerpts, read
eligibility, or assume the episode is written once.

## What it leaves open

- Whether a weakened belief's confidence should be recomputed from the evidence
  that remains.
- The episode commands' exact names, and whether read-back of a forgotten
  conversation's tombstone is shown.
- Where the parked binding lives once stories land.
