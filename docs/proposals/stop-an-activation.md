# Stopping an activation

**The question.** How does the user stop the assistant while it is working, and what
happens to work already under way?

This is the fourth proposal of the channel redesign
([#2578](https://github.com/leonapivato/ai-assistant/issues/2578)). It ships with the
conversation channel ([#2680](https://github.com/leonapivato/ai-assistant/pull/2680)):
under that channel's interim, a message written while the assistant works waits until the
running activation ends, so a correction cannot overtake the action it corrects. Stop is the
way to halt work before it acts. It is also the building block the later takeover uses
(ADR-0292 §11).

## Baseline

Wiki pages, read at wiki revision
[`b95617b`](https://github.com/leonapivato/ai-assistant/wiki/Controller/b95617b24abc2f1bbef5997ecf4b36eb6056bbc6):
[Controller](https://github.com/leonapivato/ai-assistant/wiki/Controller) ("When processing
is stopped from outside, the end entry records it before it stops") and
[Concurrent activations](https://github.com/leonapivato/ai-assistant/wiki/Concurrent-activations)
("An action already running is not stopped halfway; cancelling it afterwards is a new
action").

| ADR | What it decides today | What this proposal would do |
| --- | --- | --- |
| ADR-0292 §12 | A command is the user's explicit, structured act on a device that may send commands; a message never becomes a command. | Applied: stop is a command (§1). |
| ADR-0280 §5:3 | A pass cancelled or interrupted while the controller runs ends with the end entry `interrupted`, appended before the cancellation propagates. | Amend: a stop ends the pass with its own end entry and reason, after effects in flight have finished (§3, §4). |
| ADR-0286 §7 | A restart closes an open episode as interrupted, `hub_stopped`. | Unchanged; a stop is told apart from it (§4). |
| ADR-0261 | Cancelling is a user act between turns that ends the goal's attempt; the store decides the race with a claim; an effect already dispatched is reported, not withdrawn. | Kept, and reused: a stop refuses later claims the same way (§3). Stop does not abandon the goal (§5). |
| ADR-0060 | Cancellation must not orphan a resource a seam acquired. | Kept: what stops at once is cancelled under it. |

## The change

### 1. Stop is a command

- **Stop names one activation.** A conversation's current state carries the id of the
  activation running on it, so the device's stop control next to "working…" names it. The
  command line names it too (`assistant stop`, with the running activation of a conversation
  as the default).
- **It comes from a device that may send commands** (ADR-0292 §4), as a structured act. Typing
  "stop" is a message: under the conversation channel's interim it waits like any other, which
  is why the control exists.
- **Stopping an activation that has already ended does nothing** and says so.

### 2. What stops at once

Work with no effect on the world stops as soon as the stop is recorded: model calls, reads of
the assistant's own records, pulls such as a search or a forecast, and any phase between
them. They are cancelled under ADR-0060, so nothing they acquired is orphaned.

### 3. What finishes

- **No new effect starts after a stop.** The stop is written to the store, and an effect's
  claim made after it is refused by the store, as a cancellation's is under ADR-0261 §4:
  whichever write lands first wins, and nothing in a driver decides it.
- **An effect already dispatched finishes.** A booking already sent is not cut off halfway:
  the activation waits for its outcome, bounded by the effect's own deadline, and records it
  as done, not done or unknown. Undoing it afterwards is a new request.

### 4. How it ends

- **The episode ends with its own end entry**, `stopped`, with the reason that the user
  stopped it, so the record tells a stop from a crash or a restart (`hub_stopped`). It is
  appended once effects in flight have finished, not before.
- **No new message is written** into the conversation (ADR-0292 §11). The conversation's
  current state shows *stopped*, and any effect that finished while stopping, so the user sees
  what happened without a composed reply.
- **Messages that waited** under the conversation channel's interim are then taken in as
  usual. "Stop" followed by "actually Sunday" is how a correction overtakes work before it
  acts.

### 5. What stop does not do

- **It does not abandon the goal.** The activation's work stops; the goal it was working on
  stays as it is, its attempt recorded as stopped. The next message decides: "never mind"
  abandons it (ADR-0261's shape (a)), "go on" continues it, "make it Sunday" corrects it.
- **It does not undo anything.**
- **It does not forget.** The stopped episode is kept like any other.

### 6. Takeover uses it

In the concurrency milestone, when understanding judges that a new activation changes or
cancels running work, a rule stops the older one with this same stop. Who may cause that is
the concurrency milestone's; the mechanics are these.

## Options considered

**Stop as a message**, typing "stop". Declined: a message never becomes a command (ADR-0292
§12), and under the interim it would wait behind the work it means to stop.

**Cancel everything at once**, effects in flight included. Declined: an effect cut off
halfway leaves its outcome unknowable, which is the duplicate-booking risk the claim boundary
exists to prevent.

**Stop abandons the goal.** Declined: "stop" and "never mind" are different; the user may stop
to correct.

**Write a "stopped" message into the conversation.** Declined: ADR-0292 has a stopped
activation write nothing new, and the current state already shows it.

## Out of scope

- Stopping by words; who may trigger a takeover: the concurrency milestone.
- Stopping work not started from a conversation, such as a timer's activation: the same
  command applies, and how a device finds such an activation is the device session's.

## What it leaves open

- **The bound on waiting for an effect in flight**, when an effect has no deadline of its own.
