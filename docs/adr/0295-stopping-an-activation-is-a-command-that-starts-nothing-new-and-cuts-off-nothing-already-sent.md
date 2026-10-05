# 295. Stopping an activation is a command that starts nothing new and cuts off nothing already sent

- Status: Accepted
- Date: 2026-10-04
- Scope: [#2578](https://github.com/leonapivato/ai-assistant/issues/2578), the channel redesign: stopping an activation, which ships with the conversation channel (ADR-0293 §11:8).
- Authorization: the owner accepted proposal #2684 on 2026-10-04, at `483ae003`, and the dispatcher assigned 0295. This ADR is that proposal converted under `docs/proposals/README.md` → "When it is decided".
- **Partially supersedes** [ADR-0280](0280-an-activation-controller-runs-the-stages-by-rules-and-records-every-choice-with-the-episode.md) — **two scopes.** **§4:2's member set, in the addition alone**: `ControllerRule` gains the end entry of a stop (§3 below). **§5:3's and §5:4's `interrupted`, for a pass a stop ends**: such a pass ends with a stop's own end entry, appended where and when those clauses append `interrupted` (§3 below). Every other clause stands, §5:3 and §5:4 for every other cancellation included.
- **Partially supersedes** [ADR-0293](0293-the-hubs-chat-is-a-hosted-medium-and-a-conversation-keeps-its-own-transcript.md) — **two scopes.** **§8:3's list of endings, in the addition alone**: the current state also shows *stopped*, with the effects the stopped activation sent that finished (§3 below). **§9:1 and §10:2, for a stopped activation**: a stopped activation writes no *couldn't finish* message, as §6:17 already has it write nothing new (§3 below). Every other clause stands.

## Context

**The question.** How does the user stop the assistant while it is working, and what does
a stop guarantee about work already under way?

This is the fourth decision of the channel redesign
([#2578](https://github.com/leonapivato/ai-assistant/issues/2578)), and it ships with the
conversation channel (ADR-0293 §11:8). Under that channel's interim, a message written
while the assistant works waits until the running activation ends (ADR-0293 §6:2,
ADR-0292 §11:5), so a correction cannot overtake the action it corrects. Stop is the way
to halt work before it acts. It is also the building block the later takeover uses
(ADR-0292 §11:2).

This decision decides **what a stop guarantees**. How each phase honours those guarantees
is the phases' own design and is not decided here, as the owner ruled on 2026-10-04.

The owner accepted the proposal (#2684) on 2026-10-04 and ruled on these points, each
recorded below as the owner's ruling of that date: that the decision is the guarantees
and not each phase's behaviour; that an activation that asked a question has ended, and
the question stays open for the user to answer (§1); and that messages which waited are
taken in as usual after a stop, rather than held (§3).

The owner's direction was read, as of the proposal, from the wiki pages
[Controller](https://github.com/leonapivato/ai-assistant/wiki/Controller) (*"When
processing is stopped from outside, the end entry records it before it stops"*) and
[Concurrent activations](https://github.com/leonapivato/ai-assistant/wiki/Concurrent-activations)
(*"An action already running is not stopped halfway; cancelling it afterwards is a new
action"*), at wiki revision
[`b95617b`](https://github.com/leonapivato/ai-assistant/wiki/Controller/b95617b24abc2f1bbef5997ecf4b36eb6056bbc6).
Where this ADR and those pages differ, this ADR governs.

**The ADRs this touches**, as they stand on `main`:

| ADR | What it decides today | How this decision relates |
| --- | --- | --- |
| ADR-0292 §12:5–§12:6 | A command is the user's explicit, structured act on a device that may send commands; a message never becomes a command. | Applied: stop is a command (§1). |
| ADR-0292 §4:1 | A device's roles, source of commands among them, are assigned by the user. | Applied: a stop comes from a device that may send commands (§1). |
| ADR-0292 §11:2, §11:4 | A takeover stops the older activation; the end state owes a stopped activation never writing new output into a place. | Applied: the takeover uses this stop (§5), and a stopped activation writes nothing new (§3). |
| ADR-0280 §4:2 | `ControllerRule` has exactly the members ADR-0280 names. | Partially superseded, in the addition alone: a stop's end entry (§3). |
| ADR-0280 §5:3, §5:4 | A pass cancelled or interrupted, while the controller runs or before it is entered, ends with the end entry `interrupted`. | Partially superseded for a stop: it ends with an end entry of its own, appended at the same point (§3). |
| ADR-0293 §8:3 | The current state shows how the last activation ended: done, couldn't finish, or interrupted. | Partially superseded, in the addition alone: *stopped*, with the effects that finished (§3). |
| ADR-0293 §9:1, §10:2 | An activation that ends having written nothing writes *couldn't finish*; the adapter writes it when a pass ends without a reply. | Partially superseded for a stopped activation, which writes nothing new, as ADR-0293 §6:17 already rules (§3). |
| ADR-0293 §6:2–§6:3 | A message written while an activation runs waits, and is taken in when it ends. | Applied: a stop ends the activation, and what waited is taken in as usual (§3). |
| ADR-0293 §8 | The current state is read with the conversation and never written into it. | Extended: it carries the running activation's id, which a stop names (§1). |
| ADR-0286 §7 | A restart closes an open episode as interrupted, `hub_stopped`. | Unchanged; a stop is told apart from it (§3). |
| ADR-0261 §1, §4, §11 | A cancellation gives the goal up or corrects it, between turns; the store decides the race between it and an effect's claim; an effect already dispatched is reported, not withdrawn; a live act reaching a running turn is left undecided. | Not superseded. A stop gives nothing up, so it is not a cancellation in ADR-0261's sense (§4); it reuses §4's rule that the store decides the race (§2). |
| ADR-0060 | Cancellation must not orphan a resource a seam acquired. | Kept (§2). |

**What exists.** Nothing lets the user stop a running activation. A pass cancelled while
it runs, whatever the cause, ends with the end entry `ControllerRule.interrupted`
(ADR-0280 §5:3) and is classified `interrupted` with reason `ProcessingReason.CANCELLED`;
a restart closes what it finds open with `hub_stopped` (ADR-0286 §7:2). Between turns, the
user can abandon a goal (ADR-0261), which gives the objective up. A message typed while
the assistant works will, under the conversation channel, wait until the work is done.

## Decision

We will make stopping an activation a command that names one running activation, and we
will have a stop guarantee that nothing new starts after it, that an effect already sent
is not cut off and its outcome is recorded, and that nothing acquired is orphaned; how
each phase honours those guarantees is that phase's own design.

> **Normative.** §§1–5 govern stopping an activation, and every route an implementation
> builds for it from this ADR on.

### 1. Stop is a command

> **Normative.** A stop is a command in ADR-0292 §12:5's sense, and it names exactly one
> activation.

> **Normative.** A conversation's current state (ADR-0293 §8) carries the id of the
> activation running on it, so that a device's stop control beside "working…" names
> that activation.

> **Normative.** A stop given from the command line names its activation by the same id.

> **Normative.** A stop is accepted only as a structured act from a device that may send
> commands (ADR-0292 §4:1).

> **Normative.** The word "stop" written in a conversation is a message and never a
> stop, and under ADR-0293 §6:2's interim it waits like any other message.

That a typed "stop" would wait behind the work it means to stop is why the control
exists (ADR-0292 §12:6).

> **Normative.** A stop naming an activation that has already ended changes nothing,
> and its answer says that the activation had already ended.

An activation that asked the user a question has ended.

> **Normative.** A question an ended activation asked stays open in the conversation
> whether or not a stop names that activation, and the user disposes of it by answering
> it, "never mind" included.

That is the owner's ruling of 2026-10-04.

### 2. What a stop guarantees

> **Normative.** Nothing new starts in a stopped activation once the stop has landed.

> **Normative.** No new effect starts after a stop: an effect's claim made after the
> stop is refused by the store, as a cancellation's is under ADR-0261 §4:2, and
> whichever of the stop and the claim lands first in the store wins.

> **Normative.** An effect already sent when the stop lands is not cut off, and its
> outcome is recorded as done, not done or unknown.

> **Normative.** A stop orphans nothing the activation acquired (ADR-0060).

Which work is interrupted at once, and how each phase stops, is the phases' design, as
the owner ruled.

### 3. How it ends

> **Normative.** A stopped activation's episode ends with an end entry of a stop's own,
> a `ControllerRule` member distinct from `ControllerRule.interrupted`, from `hub_stopped`
> and from every failure's end entry, so the record tells a stop apart from a crash, a
> restart and an interruption.

The member's name, and the processing reason a stopped pass carries, are the
implementation's.

> **Normative.** A stop's end entry is appended at the point where ADR-0280 §5:3 or
> §5:4 would append `interrupted` for the same pass, whether the stop lands while the
> controller runs or before it is entered.

> **Normative.** A stopped activation writes nothing new into the conversation: no reply,
> no *couldn't finish* message (ADR-0293 §9:1, §10:2) and no message saying it stopped
> (ADR-0292 §11:4, ADR-0293 §6:17).

> **Normative.** The conversation's current state shows *stopped* as how the last
> activation started from it ended, beside ADR-0293 §8:3's done, couldn't finish and
> interrupted.

> **Normative.** The current state of a stopped activation's conversation shows each
> effect the activation sent that finished, so the user sees what happened without a
> composed reply.

> **Normative.** When a stopped activation ends, the messages waiting in its
> conversation are taken in as ADR-0293 §6:3 takes them in, and a stop holds none of
> them back.

That is the owner's ruling of 2026-10-04. Stop followed by "actually Sunday" is how a
correction overtakes work before it acts; a waiting message the user no longer wants,
they delete (ADR-0293 §5).

### 4. What a stop is not

> **Normative.** A stop abandons no goal: the goal the stopped activation was working on
> stands as it was, and what the user does next decides it.

"Never mind", "go on" and "make it Sunday" are each such a next step. A stop is
therefore not a cancellation in ADR-0261 §1's sense, which gives the objective up or
replaces it.

> **Normative.** A stop undoes nothing, and undoing an effect a stopped activation sent
> is a new request.

> **Normative.** A stopped activation's episode is kept like any other (ADR-0287), and a
> stop forgets nothing.

### 5. Takeover uses it

> **Normative.** When a new activation takes over running work (ADR-0292 §11:2), the
> older one is stopped by this stop and carries every guarantee of §§2–4.

Who may cause a takeover is the concurrency milestone's.

### 6. Relationship to earlier decisions

> **Normative.** This ADR supersedes ADR-0280 and ADR-0293 in the scopes its header
> names, and no clause of any other ADR.

> **Normative.** This numbered draft records its replacements on the status line and in
> a dated header note of ADR-0280 and ADR-0293, atomically with this ADR under ADR-0070
> and ADR-0082, preserving their ratified bodies. The replacements take effect on this
> ADR's ratification.

A stop exists only once it is built, so until then the scopes replaced are empty and
every pass and every ending is governed by the clauses as they stand.

| Earlier decision | Where it goes |
| --- | --- |
| ADR-0280 §4:2's member set, in the addition | §3 (a stop's end entry) |
| ADR-0280 §5:3, §5:4, for a pass a stop ends | §3 (a stop's end entry, at the same point) |
| ADR-0293 §8:3's endings, in the addition | §3 (*stopped*, with the effects that finished) |
| ADR-0293 §9:1, §10:2, for a stopped activation | §3 (nothing new written) |

## Consequences

**What becomes clear.** The user can halt the assistant before it acts, and a correction
can then overtake the work it corrects: stop, and the message that waited is taken in.
What a stop promises is the same in every phase: nothing new starts, nothing sent is cut
off halfway, and nothing acquired is left behind. Stopping, abandoning, undoing and
forgetting are four different acts, and a stop is only the first. The record and the
conversation's current state both say that the activation was stopped, apart from a
crash, a restart or an interruption, without a message written into the conversation.
The concurrency milestone's takeover has its stop already defined.

**What it costs.** Each phase has to honour the guarantees, and the claim race needs a
write the store can decide against, so building a stop reaches every phase that starts
work or sends an effect. The command and the stop's end entry change `AssistantEngine`
and `core/types.py`, a contract change this ADR decides under golden rule 5. An effect
already sent may still take as long as it takes, so a stop is not instant.

**What follows from it.**

1. **The build**, in the conversation channel's milestone (ADR-0293 §11:8): the stop
   command and its control, the running activation's id in the current state, the
   store's refusal of a claim made after a stop, the stop's end entry, and *stopped* in
   the current state.
2. **The phases' design** of how each honours a stop.
3. **The takeover**, in the concurrency milestone, which uses this stop.

**What stays open.** Neither is decided here.

- **How each phase honours a stop**: the phases' design.
- **How long to wait for an effect already sent** when it has no deadline of its own.

**Out of scope.**

- Stopping by words, and who may trigger a takeover: the concurrency milestone.
- Finding an activation not started from a conversation, such as a timer's: the same
  command applies; how a device finds it is the device session's.

## Alternatives considered

- **Stop as a message**, typing "stop". Declined: a message never becomes a command
  (ADR-0292 §12:6), and under the interim it would wait behind the work it means to
  stop.
- **Cancel everything at once**, effects in flight included. Declined: an effect cut off
  halfway leaves its outcome unknowable, which is the duplicate-booking risk the claim
  boundary exists to prevent.
- **Stop abandons the goal.** Declined: "stop" and "never mind" are different; the user
  may stop to correct.
- **A stop also holds the waiting messages** until the user sends something new.
  Declined by the owner: the usual reason to stop is to correct, and the correction is
  usually already waiting.
- **Write a "stopped" message into the conversation.** Declined: ADR-0292 §11:4 has a
  stopped activation write nothing new, and the current state already shows it.
