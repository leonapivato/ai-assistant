# 317. An activation that chose to say nothing has finished

- Status: Partially superseded by ADR-0356 (§2:2, in its subject alone: an activation that made no message call writes nothing; §3:4's *a message a round wrote*, in its subject alone: a message call)
- Date: 2026-10-13
- Scope: the phases, milestone M43 ([#2815](https://github.com/leonapivato/ai-assistant/issues/2815)): how an activation started from a conversation ends when planning chose to write nothing, and where the *couldn't finish* message is written ([#2943](https://github.com/leonapivato/ai-assistant/issues/2943)).
- Authorization: the owner ruled this decision's content on 2026-10-13 in #2943, option A: silence is a normal ending. The dispatcher assigned 0317 and authorized ratifying it once its reviews are green.
- Changes no `core` type or Protocol and nothing the wire carries.
- **Partially supersedes**
  [ADR-0293](0293-the-hubs-chat-is-a-hosted-medium-and-a-conversation-keeps-its-own-transcript.md)
  (§9:1 whole: an activation whose planning chose to write nothing has finished and writes
  no message, and *couldn't finish* is written where §3 below names) and
  [ADR-0307](0307-a-planning-round-is-one-model-response-that-writes-its-own-message-keeps-episode-notes-and-names-what-it-was-shown-by-label.md)
  (§3:7, in the addition alone: a stage's failure that ends the activation also writes *couldn't finish*, whatever
  earlier rounds wrote).
- Partially superseded: 2026-10-30 by ADR-0356 — §2:2, in its subject alone: an activation that made no message call writes nothing into the conversation, where it said *with every round's text empty*, since a round's text is no message (ADR-0356 §7:3). §3:4's *a message a round wrote*, in its subject alone: a message call the round proposed. Every other clause stands. This replacement takes effect on ratification of ADR-0356. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.

## Context

**Two rulings meet.** ADR-0315 §4:2, with ADR-0307 §3:2, has a round with nothing the
user will want to hear write no message. Planning's instruction tells it to leave the
text empty only where the user asked nothing of the round. ADR-0293 §9:1 has an
activation started from a conversation that ends having written nothing write the fixed
*couldn't finish* message, listing any effects that did happen.

**What the M43 acceptance run found** (#2943, activation `5da9b71f`). The user answered
"sounds good" to the assistant's acknowledgement. Planning's first round wrote no text and
restated three facts already remembered; its second round wrote no text and made no
call. Nothing failed: every stage was `done` and the controller ended on `nothing_due`.
Because nothing was written, §9:1 wrote *couldn't finish*, listing the two `remember`
calls that ran. The episode froze `failed / processing_failed`, and the conversation's
current state read *couldn't finish*. Any content-free reply, such as "ok", "thanks" or
"sounds good", where planning rightly stays silent, is shown to the user as a failure.

**The record gap** (#2943's first comment). The diagnostic record (ADR-0314) ended that
activation on `nothing_due` and `done`, and the activation viewer (ADR-0316) showed it
finished, with no *could not finish* badge. The user read *couldn't finish*. An owner
reading the record could not see what the user saw.

**The owner's ruling** (#2943, 2026-10-13, option A). An activation started from a
conversation ends done, with no reply, when planning's last round makes no call and
writes no text: planning chose silence, and that is a finish. *Couldn't finish* stays for
an activation that did not finish: the round limit ended it; a stage failed or hit its
deadline; or a message planning wrote was not delivered, because authorizing refused it
or it was lost. A stop still writes nothing (ADR-0295 §3:3). The fix lane checks that
each remaining cause of *couldn't finish* shows in the record and the viewer. The ruling
amends ADR-0293 §9:1, so an amending ADR comes first and the fix follows.

## Decision

We will treat an activation started from a conversation as finished when its last round
made no call other than a tidy-up, whatever its rounds wrote, so that one which wrote
nothing ends done with no message; and we will write *couldn't finish* only where the
round limit, a stage's failure or a deadline ended the activation, or where a message it
wrote was refused or lost and no later message of it reached the conversation.

### 1. Status and delivery

> **Normative.** This document remains `Proposed` until the reviews
> `CONTRIBUTING.md` → "Finishing an ADR PR" requires have returned green on one tree
> and the owner's ruling and the dispatcher's authorization to ratify stand.

> **Normative.** No lane implements this decision until it has merged `Accepted`.

> **Normative.** One lane implements it: the ending in `PhasePath.run`, the citations
> §6 names, and tests of each case §2 and §3 decide, in one change.

### 2. A silent ending

> **Normative.** An activation started from a conversation has finished, and ends done,
> when its last round made no call other than a tidy-up (ADR-0315 §2:2–§2:3), unless a
> stop, a cancellation or a restart ended it, or §3 has *couldn't finish* written for it.

> **Normative.** An activation that finishes with every round's text empty writes nothing
> into the conversation: no message, and no *couldn't finish*. Planning chose silence
> (ADR-0307 §3:2, ADR-0315 §4:2), and that is an ending, not a failure.

> **Normative.** Its episode freezes as an ordinary result, `completed / returned`: the
> row of ADR-0275 §5:3's table for any other ordinary result. It is not `failed`, and it
> is not `completed / no_content`, which is the row for speech that produced no words.

> **Normative.** The conversation's current state shows it ended done (ADR-0293 §8:3).

The effects a silent activation's earlier rounds made are not listed to the user, since
nothing is written. They are in the episode's rounds and their effect records, as any
finished activation's are.

### 3. *Couldn't finish*

> **Normative.** Where §3:2–§3:4 name a case, the fixed *couldn't finish* message is
> written into the conversation the input came from, listing each effect the activation
> made that is done and each whose outcome is unknown, an unknown one as unknown. It is
> written in no other case.

> **Normative.** It is written where the round limit ended the activation (ADR-0315
> §2:4), whatever earlier rounds wrote. This is ADR-0307 §3:7 as written.

> **Normative.** It is written where a stage's failure or a deadline ended the activation,
> whatever earlier rounds wrote. A failure a stage tolerates, after which the activation
> goes on (such as recall's under ADR-0281 §5), ends nothing and writes nothing; where the
> activation then finishes, §2 decides its ending. The controller's loop guard ending the
> activation (ADR-0280 §4:6, in the scopes later decisions give it) counts as a stage's
> failure ending it, and so does a failure after the activation took in any of the
> conversation's waiting messages and before its first stage ran. A failure before it
> took in any writes nothing, since the activation did nothing.

> **Normative.** It is written where a message a round wrote was refused by authorizing,
> or its write did not come back done (ADR-0306 §5), and no later message of the
> activation was recorded in the conversation. Where a later one was, the refused or lost
> message writes no *couldn't finish*, and the activation ends as §2:1 decides.

> **Normative.** Wherever it is written, the activation did not finish: its episode
> freezes `failed`, classified by ADR-0275 §5:3's table, with the round limit, the loop
> guard and §3:4's case each `failed / processing_failed`; and the current state shows
> *couldn't finish* (ADR-0293 §8:3).

> **Normative.** A stop, a cancellation and a restart write nothing into the conversation,
> and §3 reaches none of them (ADR-0295 §3:3, ADR-0293 §9:2).

§3:2 and §3:3 apply whatever earlier rounds wrote because a message already sent does not
tell the user that the rest was cut short. §3:4 applies whatever earlier rounds wrote for
the same reason: an earlier "Let me check…" that reached the user, followed by a final
answer that was refused or lost, leaves them waiting on an answer that never comes. It is
excused only where a later message was recorded, because a later round that wrote again
has answered: a refused or lost message brings no round of its own (ADR-0315 §2:1 counts
calls, not messages), but a round that made calls beside it brings one, which may write.

### 4. The record and the viewer

> **Normative.** Nothing records in the diagnostic record that *couldn't finish* was
> written. The record shows its cause, and `phase_path.py` writes no entry of its own
> (ADR-0314 §4:2).

> **Normative.** The lane that implements this decision confirms, in its pull request,
> that each cause §3 names shows in the record as this clause has it, and in the viewer:
> the round limit as the controller's end entry `round_limit_reached`; a stage's failure
> or a deadline as that stage's controller step ended failed or timed out, with the end
> entry naming it; the loop guard as the end entry `stage_repeated`; and a refused message
> as authorizing's verdict on the message. Where one does not show, the lane files an
> issue and does not widen its change to fix it.

> **Normative.** Two causes gain no entry in the record. A message write that did not come
> back done has none, since acting and the message writes write none (ADR-0314 §4:3), and
> its effect record holds its outcome. A failure before the first stage ran has none,
> since no source ran to write one, and the episode's end entry `ended_before_controller`
> holds it.

> **Normative.** The viewer gains no reading for this decision. It shows the round limit,
> a stage's failure, a deadline and the loop guard through its *could not finish* badge,
> and a refused message through its *refused* badge (ADR-0316 §3:1).

Once a silent activation ends done, the record's `nothing_due` and `done` are what the
user saw, which closes #2943's gap for the case it found. A lost message whose
conversation is gone takes *couldn't finish* nowhere, since the place is gone too; one
lost to a store failure may leave the record showing an end the user read as
*couldn't finish*, with the effect record holding why.

### 5. Planning's instruction

> **Normative.** The lane that implements this decision does not change the text of
> planning's instruction. It re-grounds the comment beside the instruction's reply part,
> which cites ADR-0293 §9:1, on this decision.

The instruction already tells planning to leave the text empty only where the user asked
nothing of the round, and to say so when it acts on what the user asked. Both still hold:
the second is how the user hears that the assistant acted, not a guard against
*couldn't finish*.

### 6. The code it binds

| Code | Change |
| --- | --- |
| `PhasePath.run` | Its ending: a pass that returned with nothing written ends done (§2); *couldn't finish* is written for the round limit, the loop guard and §3:4's case where it returned, and for every failure it re-raises, as today (§3) |
| `ActivationState.unfinished` | Set for the round limit, the loop guard and §3:4's case alone, never for a silent ending (§2:3, §3:5) |
| `terminal_status` | Unchanged rows; its docstring cites this decision |
| Planning's instruction | Its text unchanged; the comment on its reply part cites this decision, not ADR-0293 §9:1 (§5:1) |
| `PhasePath.unbegun` | Unchanged in what it does: it writes the message for §3:3's failure after messages were taken in and before the first stage ran; it cites this decision where it cites ADR-0293 §9:1 |
| `PhasePath._couldnt_finish` and the module docstring of `phase_path.py` | Each cites this decision where it cites ADR-0293 §9:1 for when the message is written |
| `couldnt_finish` in `orchestration/chat.py` | Unchanged: the fixed message and how it lists the effects (§3:1) |
| `ActivationEnding` | Unchanged members: `done` covers a silent ending (§2:4) |
| The diagnostic record, its emitters and the viewer | Unchanged (§4) |

### 7. Relationship to earlier decisions

| Earlier decision | What changes |
| --- | --- |
| ADR-0293 §9:1 | Whole: §2 decides that a silent activation has finished, and §3 where *couldn't finish* is written and what it lists |
| ADR-0293 §8:3 | Nothing: a silent ending is done, and *couldn't finish* is shown where §3 writes it |
| ADR-0293 §9:2 | Nothing: a restart writes nothing (§3:6) |
| ADR-0293 §10:2 | Nothing: it governs the adapter that wrote the compose stage's reply until the phases sent messages |
| ADR-0295 §3:3 | Nothing: a stop writes nothing (§3:6); its record on ADR-0293 §9:1 names a clause §3:6 now carries |
| ADR-0307 §3:2 | Nothing: a round whose text is empty writes no message |
| ADR-0307 §3:7 | In the addition alone: a stage's failure that ends the activation also writes *couldn't finish*, whatever earlier rounds wrote (§3:3). The round limit and a deadline stand as written, and the message is the one §3:1 describes |
| ADR-0313 §4:5 | Nothing: an event, whose place takes no message, writes none, and returns how it ended |
| ADR-0314 §4:2–§4:3 | Nothing: no entry is added (§4) |
| ADR-0315 §2, §4:2 | Nothing: §2:1 reads the last round as ADR-0315 §2:2–§2:3 end it |
| ADR-0275 §5:3 | Nothing: a silent ending is its table's ordinary result |
| ADR-0316 §3 | Nothing: the viewer reads the causes as it does (§4:4) |

> **Normative.** This numbered draft records its replacements on the status lines and in
> a dated header note of ADR-0293 and ADR-0307, atomically with this ADR under ADR-0070
> and ADR-0082, preserving their ratified bodies. The replacements take effect on this
> ADR's ratification.

## Consequences

**What becomes possible.**
- A content-free reply, such as "thanks", ends quietly, as a person would let it, and is
  no longer shown to the user as a failure.
- *Couldn't finish* means the assistant did not finish, so the user can trust it, and an
  owner reading the record sees its cause there.

**What it costs.**
- Where planning wrongly stays silent on a request that wanted an answer, the user now
  sees no reply and a done state, where before they saw *couldn't finish*. Planning's
  instruction is what guards that (§5), and a silent ending is visible in the record as a
  last round with empty text.
- The effects a silent activation made are not listed to the user. They are in its
  episode and its effect records.

**What stays open.**
- A message lost to a store failure, and a failure before the first stage ran, leave the
  diagnostic record without the cause of the *couldn't finish* written for them (§4:3).
  The effect record and the episode's end entry hold each.
- The viewer also badges a failure a stage tolerated as *could not finish*, where §3:3
  writes none ([#2973](https://github.com/leonapivato/ai-assistant/issues/2973)).

## Alternatives considered

- **Planning always says something in a conversation** (#2943's other option). Rejected
  by the owner: it would make planning answer "thanks", which a person would not.
- **`completed / no_content` for a silent ending.** Rejected: that row is for speech that
  produced no words, and spoken conversation retired at the cutover (ADR-0313 §3).
- ***Couldn't finish* for a refused or lost message only where none of the activation's
  messages reached the conversation.** Not chosen: a round that wrote filler such as
  "Let me check…", followed by a final answer that was refused or lost, would leave the
  user waiting with no *couldn't finish*, since the filler reached them.
- **Every refused or lost message writes *couldn't finish*, even where a later message
  was recorded.** Not chosen: a later round that wrote again has answered.
- **An entry recording that *couldn't finish* was written.** Rejected: `phase_path.py`
  writes no entry (ADR-0314 §4:2), and each cause but the two §4:3 names is in the record
  already.
- **The viewer badging a refused message as *could not finish* where no message was
  allowed.** Not chosen: its *refused* badge already shows the cause, and the viewer is
  outside this decision's implementing lane.
