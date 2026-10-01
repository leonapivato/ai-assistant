# An episode is the experience of processing its activation

**The question.** What belongs on an episode, so that it records an activation the
same way on every channel and carries nothing that only one kind of channel, or one
reader, needs?

**The answer proposed.** An episode is the experience of processing one activation:
what arrived and how it arrived, what processing understood, recalled, decided and
did, what went out, and how it ended. Three other kinds of thing sit beside an
experience rather than in it: indexes derived from it (its search text), its
disclosure, derived from where it arrived and what processing read, and annotations
the world adds afterwards (spoken delivery). Mechanics belong to the trace store,
not the episode.

This proposal is the second of three steps (ADR-0283's Consequences). It applies the
definition to the parts of today's episode that name a channel, carry a read
policy, or restate other fields. The third step, the episode store as the one
record, applies it to the rest: the episode stops being a `MemoryBase`, and its
belief-shaped fields (confidence, validity, topics, importance) go.

## Baseline

Wiki, read at `ea98b15`:

- [Episodes](https://github.com/leonapivato/ai-assistant/wiki/Episodes): "the
  assistant's record of one activation: what arrived and where from, what the
  assistant understood and recalled, which phases ran, what it replied, and how
  processing ended"; and "Outside content stays outside … marked as a report
  received, never through its raw input".
- [Channels](https://github.com/leonapivato/ai-assistant/wiki/Channels): a channel
  is a medium held in the hub; it declares a description and requirements (#2578
  holds the detail); "A channel's identity grants nothing … Only the user's own
  input carries authority."

ADRs, at `a46bd56c`:

- ADR-0274 §4: the channel dispatch table (which payloads, reply shapes and options
  each channel type accepts), and the informational-event summary stage.
- ADR-0275 §4 (`EpisodeProcessingRecord`, `RecordedChannelTrigger`,
  `EpisodeResponseKind` and its pairing with `outcome`), §7 (`model_eligible` and
  `episode_model_eligible`), §8:5 (conversational `content` and `disposition`), §9:6
  (raw input kept out of automatic model inputs).
- ADR-0221 §1–§3: `outcome` is the reply, `ExchangeDisposition` is the typed result,
  and the render rule that reads both.
- ADR-0276 §4 and ADR-0281 §3, §4, §6: the episode window and recall, each of which
  admits an episode's input text and tells an outside report from the user's words.
- ADR-0280 §6: the stage entries (`stage`, `due`, times, `outcome`).
- ADR-0283 §3, §4, §11: `channel_episodes` takes `episode_model_eligible`; history
  and the observer filter on it.

## What is wrong today

An episode names channel types, and readers branch on those names:

1. **`response_kind`** has the values `conversation_reply` and
   `informational_summary`. It restates the record: `none` is "no `outcome`", a
   summary is "the channel is `informational_event`", and a reply is the rest. Its
   only reader that branches is the validator pairing it with `outcome`; the CLI
   shows it as a label.
2. **The trigger's validator** (`RecordedChannelTrigger`) repeats ADR-0274 §4's
   dispatch table for `informational_event` and `conversation`, and every trigger
   carries a `conversation` field of options that only a conversation uses.
3. **Recall and understanding test for one channel type.** Recall marks an episode
   as outside provenance, and keeps its raw input out of excerpts, where
   `channel_type == "informational_event"`. Understanding tells the model an input is
   "a report … never something the user said" on that type, and "the message the
   user just sent" on `conversation`. What both mean is *who the input came from*. A
   second outside channel, a mail reader or a calendar feed, would be read as the
   user's own words, because it is not the one name tested.
4. **The step's verdict is conversational and off the stage.**
   `ExchangeDisposition` is the only record of what became of a step or a route
   (denied, no capable tool, refused, …), and it is set only where a conversational
   capture ran. The stage entries record that `drive` ran, not what it concluded.
   Renderers also use it to decide whether `outcome` is a reply.
5. **`model_eligible`** is a read policy, not something that happened. ADR-0275 §7
   made it a compatibility flag so the reads from before M36 kept seeing what they
   saw; it is false exactly when a pass never reached the conversational capture:
   every event, cancellation, transcription failure, wordless speech, and failure
   before capture. The owner ruled the compatibility no longer needed (2026-09-27).
6. **`content` is composed per channel.** A conversational episode's `content` is
   the user's words, the plan's rationale and a selected-tool line; any other
   episode's is its latest understanding's meaning, or the constant `Recorded
   activation; inspect its processing record.`
7. **`reply_degraded` and `spoken_degraded`** name a conversation's reply and
   speech rather than the response and the output.

## The change

### The episode records how its input arrived, as the channel declared it then

At admission, the trigger records what the channel declared about its input:
whether it is **the user's own input** or **outside content**. The value is taken
from the channel's declaration and fixed on the episode; it is part of how the input
was perceived, so an episode does not change from an outside report into the user's
words when a channel is later reconfigured or removed.

Until #2578 gives channels their declarations, the declaration lives with the
channel dispatch in `channel_validation`: `informational_event` declares outside
content, `conversation` declares the user's own input, and a channel type with no
declaration is refused at admission. The record names no channel type in any
rule; `channel_type` stays on it as an opaque identity.

Recall's provenance and excerpt, understanding's "received as", and the episode
window read the recorded origin. No reader tests a channel type.

The trigger's validator keeps only what is true of every trigger. Which payloads,
reply shapes and options a channel accepts is checked at admission, where it is
checked already, and the conversation options leave the trigger: what of them is
experience (that a reply was spoken, that the user referred to an earlier episode)
is recorded in the parts that use it.

### The response is what went out on the channel

`outcome` is the text the activation sent back on its channel, or nothing.
`response_kind` is removed, and so is its pairing validator. The CLI derives its
label from the channel's recorded origin and whether there is a response.

`reply_degraded` and `spoken_degraded` become `response_degraded` and
`output_degraded`, with the same meanings on every channel.

### The verdict is part of the stage that reached it

The `drive` stage's entry records the step's verdict (a `Disposition`) and the
plan's rationale; the routing stage's entry records the route's outcome (a
`RouteOutcome`). Every channel records them the same way, so an event that drives a
step keeps its verdict too. `EpisodicMemory.disposition` and `ExchangeDisposition`
are removed; renderers read the verdict from the stage entry, and "is `outcome` a
reply" becomes "is there a response".

### `model_eligible` is retired

It is removed from the processing record, from `MemoryStore.search` and `select`,
and from ADR-0283's `channel_episodes`. Every episode on a channel appears in its
history, failures and interruptions included, rendered with its status. The
observer reads them too: what the user said is evidence whether or not the
assistant managed to answer, and the status says the pass did not finish.

A reader that should skip an unfinished or failed episode reads the status, which
says so directly.

### `content` is derived the same way on every channel

`content` is the latest understanding's meaning, or, where the activation has no
understanding, one line built from its status and reason. It is what the store
embeds and searches. The user's own words reach a model through the renderers,
from the trigger, where ADR-0276 and ADR-0281 already admit them and now in history
too; outside content still reaches a model only through its meaning.

This changes retrieval of conversational episodes: they match on their meaning
rather than their raw words, as events already do.

### Cutover

`EPISODE_RECORD_FORMAT` advances, the wire protocol bumps, and the hub moves to a
fresh data directory. No migration.

## Options considered

- **Look the origin up from the channel when reading.** Fewer fields, but an
  episode's reading would change with the channel's configuration. The origin is
  part of how the input was perceived, so it is fixed at admission.
- **Derive disclosure from the channel alone.** An episode carries what processing
  read, a recalled private belief included, so its disclosure is at least as
  restrictive as what flowed in. This step leaves `placement` as it is; the third
  step derives it.
- **Delete the verdict with `disposition`.** Nothing else on the episode records
  it, and renderers need it.
- **Keep `content` as the raw words for conversations.** Preserves today's
  retrieval exactly, but keeps a per-channel composition, and outside content would
  still need a different rule.
- **Take the episode off `MemoryBase` here.** It is the full form of the definition,
  but it touches every reader that treats an episode as a memory record, and the
  third step restructures the store anyway.

## ADRs it would touch

ADR-0221 (§1–§3), ADR-0274 (§4's table as a record validator; the summary stage's
response role), ADR-0275 (§4, §7, §8:5, §9:6), ADR-0276 (§4), ADR-0280 (§6's stage
entry gains fields), ADR-0281 (§3, §4, §6), ADR-0283 (§3, §4, §7's last clause,
§11).

## What it leaves open

- What each kind of channel declares beyond the origin of its input (#2578).
- Whether the informational-event summary stage should stay. Nothing in the repo
  submits an informational event except tests, and understanding already writes the
  event's meaning; that is ADR-0274's processing, not the record's shape.
- `BEGIN_CONVERSATION` and `EVENT_SUMMARY` in the controller's stage vocabulary,
  which name channel types; they belong to the controller's design.
- `Capture.modality`, which repeats the trigger's payload modality, and the other
  `MemoryBase` fields: the third step.
- Whether importance and story membership are annotations on an episode or
  relations the stories layer (M40) holds.
- Which mechanics in today's record (elided counts, stage times) belong in the trace
  store instead.
