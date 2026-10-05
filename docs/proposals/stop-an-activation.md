# Stopping an activation

**The question.** How does the user stop the assistant while it is working, and what does a
stop guarantee about work already under way?

This is the fourth proposal of the channel redesign
([#2578](https://github.com/leonapivato/ai-assistant/issues/2578)). It ships with the
conversation channel (ADR-0293, from
[#2680](https://github.com/leonapivato/ai-assistant/pull/2680)): under that channel's
interim, a message written while the assistant works waits until the running activation
ends, so a correction cannot overtake the action it corrects. Stop is the way to halt work
before it acts. It is also the building block the later takeover uses (ADR-0292 §11).

This proposal decides **what a stop guarantees**. How each phase honours those guarantees is
the phases' own design, not decided here *(owner, 2026-10-04)*.

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
| ADR-0280 §5:3 | A pass cancelled or interrupted while the controller runs ends with the end entry `interrupted`, appended before the cancellation propagates. | Amend: a stop ends the pass with an end entry of its own (§3). |
| ADR-0286 §7 | A restart closes an open episode as interrupted, `hub_stopped`. | Unchanged; a stop is told apart from it (§3). |
| ADR-0261 §4 | The store decides the race between a cancellation and an effect's claim; an effect already dispatched is reported, not withdrawn. | Reused: the store refuses an effect's claim made after a stop (§2). |
| ADR-0060 | Cancellation must not orphan a resource a seam acquired. | Kept. |

## The change

### 1. Stop is a command

- **Stop names one activation.** A conversation's current state carries the id of the
  activation running on it, so the device's stop control next to "working…" names it; the
  command line names it too.
- **It comes from a device that may send commands** (ADR-0292 §4), as a structured act.
  Typing "stop" is a message: under the conversation channel's interim it waits like any
  other, which is why the control exists.
- **Stopping an activation that has already ended does nothing**, and says so. An activation
  that asked the user a question has ended; the question stays open in the conversation, and
  the user answers it, "never mind" included *(owner)*.

### 2. What a stop guarantees

- **Nothing new starts after a stop.** In particular, no new effect: an effect's claim made
  after the stop is refused by the store, as a cancellation's is under ADR-0261 §4. Whichever
  write lands first wins.
- **An effect already sent is not cut off**, and its outcome is recorded: done, not done or
  unknown. Undoing it afterwards is a new request.
- **Nothing it acquired is orphaned** (ADR-0060).

Which work is interrupted at once, and how each phase stops, is the phases'.

### 3. How it ends

- **The record says it was stopped.** The episode's end entry is a stop's own, telling it
  apart from a crash, a restart (`hub_stopped`) or an interruption.
- **Nothing new is written into the conversation** (ADR-0292 §11). The conversation's current
  state shows *stopped*, and any effect that finished, so the user sees what happened without a
  composed reply.
- **Messages that waited** under the conversation channel's interim are then taken in as
  usual *(owner)*. Stop followed by "actually Sunday" is how a correction overtakes work
  before it acts; a waiting message the user no longer wants, they delete.

### 4. What a stop is not

- **Not abandoning.** The goal the activation was working on is not given up by the stop.
  What the user does next decides, for example "never mind", "go on" or "make it Sunday".
- **Not undoing.**
- **Not forgetting.** The stopped episode is kept like any other.

### 5. Takeover uses it

In the concurrency milestone, when a new activation takes over running work (ADR-0292 §11),
the older one is stopped with this same stop and carries its guarantees. Who may cause that
is the concurrency milestone's.

## Options considered

**Stop as a message**, typing "stop". Declined: a message never becomes a command (ADR-0292
§12), and under the interim it would wait behind the work it means to stop.

**Cancel everything at once**, effects in flight included. Declined: an effect cut off halfway
leaves its outcome unknowable, which is the duplicate-booking risk the claim boundary exists
to prevent.

**Stop abandons the goal.** Declined: "stop" and "never mind" are different; the user may stop
to correct.

**A stop also holds the waiting messages** until the user sends something new. Declined
(owner): the usual reason to stop is to correct, and the correction is usually already
waiting.

**Write a "stopped" message into the conversation.** Declined: ADR-0292 has a stopped
activation write nothing new, and the current state already shows it.

## Out of scope

- Stopping by words, and who may trigger a takeover: the concurrency milestone.
- Finding an activation not started from a conversation, such as a timer's: the same command
  applies; how a device finds it is the device session's.

## What it leaves open

- **How each phase honours a stop**: the phases' design.
- **How long to wait for an effect already sent** when it has no deadline of its own.
