# 343. A join is taken pending its reader's marking, and every route by which an activation leaves running settles it first

- Status: Partially superseded by ADR-0349 (§2:1–§4:3, whole: no join is taken by code, so none is pending)
- Date: 2026-10-21
- Scope: how ADR-0332's join (its §3:6) is ordered against the reader's marking of the joined messages (its §3:18). A join is taken pending that marking, and the activation commits, is taken over, ends and has its episode frozen only once each pending join is settled. A joined reply's quoted message and recall run again per understanding version are not decided here (§5).
- Dependency: [ADR-0332](0332-activations-run-side-by-side-across-places-and-one-at-a-time-within-one-a-new-input-joins-the-running-activation-until-it-acts-and-a-place-waits-a-moment-before-it-starts.md), [ADR-0280](0280-an-activation-controller-runs-the-stages-by-rules-and-records-every-choice-with-the-episode.md), [ADR-0293](0293-the-hubs-chat-is-a-hosted-medium-and-a-conversation-keeps-its-own-transcript.md) and [ADR-0323](0323-a-telegram-chat-with-the-owners-bot-is-a-line-to-the-assistant-and-connecting-it-approves-what-the-line-carries.md), as their status lines leave them.
- Authorization: the owner, 2026-10-21: "Dont draw the line who ratifies what, Ill just check in and if I see something wrong I'll give input to you". Under that standing delegation the coordinator ruled the reading this decision writes down, on PR #3294's adjudication request ([the ruling](https://github.com/leonapivato/ai-assistant/pull/3294#issuecomment-6312549411), answering [the request](https://github.com/leonapivato/ai-assistant/pull/3294#issuecomment-6312507866)). The dispatcher assigned 0343, and ratifies it under that delegation.
- **Changes no contract.** No shared type changes, no Protocol changes, and nothing the wire carries or a record stores changes, so the protocol version does not move. It amends clauses of a contract-surface decision, so both review lenses run on it.
- **Partially supersedes**, in the clauses §6's first table names: ADR-0332.
- Partially superseded: 2026-10-25 by ADR-0349 — §2:1–§4:3, whole: ADR-0332's joining by code is replaced, so no join is taken pending a marking and no route out of running waits for one. A message is marked taken in by the activation that admitted it, and absorbing it marks nothing again (ADR-0349 §7, §8:8). Every other clause stands. This replacement takes effect on ratification of ADR-0349. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; the ratified body below is preserved.

## Context

In this document a bare section reference, such as §3:2, is to this decision's own clauses.
ADR-0332's are always written with its number, such as ADR-0332 §3:6.

**The two clauses.** ADR-0332 §3:6 takes a join "only where the activation's committed mark
and its stop mark are both unset, in one step with no await between that check and appending
the input to the activation's state". ADR-0332 §3:18 has the readers "mark a joined message
as taken in by the activation it joined, as at admission (ADR-0293 §6:8, ADR-0323 §5:8)". At
admission the marking comes before anything acts on the message: ADR-0293 §6:8 marks a
message taken in "when its activation is admitted", and ADR-0323 §5:8 records which updates
the line took in and by which activation. The reader's marking is a store write, so it
awaits, and ADR-0332 §3:6's step cannot await. ADR-0332 does not say how the two are
ordered.

**What the order decides.** ADR-0332's step 3, PR #3294, has been through five review
rounds under two holders, each round finding a consequence of the order on another route:

- **Joining first, then marking** (round 1). Between the append and the marking, the joined
  message existed only in memory. A lost marking was replayed after a restart, a joined
  message was confirmed before its episode recorded it, and a failed marking skipped a
  `/stop`.
- **Marking first, then joining**, with an in-memory retake (round 2). The retake was lost on
  a restart (round 3).
- **Joining pending the marking** (rounds 3 to 5). This has held across restarts. What the
  rounds found was how far the pending state reaches: the terminal paths and the takeover,
  whose conditions ADR-0332 §4:6 states exhaustively (round 4), and the deadline, which
  acting's wait for the marking did not respect (round 5).

The round-5 holder asked for a ruling, and for the ordering to be written into ADR-0332 so
that it is specified rather than found one route at a time. The coordinator ruled the third
reading. ADR-0332 §3:6's append is the pending entry, so the input is in the activation's
state from that step. ADR-0332 §3:18's "as at admission" keeps a joined message unread until
its marking lands. ADR-0332 §4:6's conditions are exhaustive, so a pending join refuses no
takeover, which waits for it instead. This decision writes that ruling down.

## Decision

We will take a join pending its reader's marking. A pending join counts toward
`join_limit`, and nothing reads it as the activation's input until the marking confirms it,
for exactly the messages the store marked. A marking that marks nothing releases it, and its
input waits. An activation leaves running by no route until every pending join is settled.
Each wait is one marking write, and inside a stage the pass's deadline also bounds it.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the authorization to
> ratify stands. An assigned number or a green review alone does not change its status.

> **Normative.** The implementation is ADR-0332 step 3's pull request, #3294, and no other
> lane. It merges only after this decision merges `Accepted`.

### 2. A join taken pending its marking

> **Normative.** ADR-0332 §3:6's step appends the input to the activation's state as a
> **pending join**: taken, and awaiting the reader's marking of its messages as taken in by
> that activation (ADR-0332 §3:18).

> **Normative.** A pending join is a join the activation has taken. It counts toward
> `join_limit`, for ADR-0332 §3:3's fifth condition and for ADR-0332 §4:6's, until it is
> released.

> **Normative.** A pending join is no part of the activation's input until it is confirmed.
> No stage and no rule reads it, the commitment step's check does not read it (ADR-0332
> §3:5), another place is not shown it (ADR-0332 §4:1), and no episode records it
> (ADR-0332 §3:16).

> **Normative.** Once the reader's marking has ended, however it ended, the join is
> confirmed for exactly the messages the store marked taken in by that activation. Those
> messages are then the activation's joined input, and the episode records the join with
> them alone.

> **Normative.** Where the store marked none of the join's messages, because the marking
> failed or found nothing to mark, the join is **released**. It is undone and no longer
> counts toward `join_limit`, and what of its input the place still holds untaken waits
> under ADR-0332 §2:4 and §3:4.

> **Normative.** A confirmed join's `joined_at` (ADR-0332 §7:1) is the instant ADR-0332
> §3:6's step took it.

So the reader's bookkeeping names the activation that took each message in, and no message
lives only in memory, as at admission. A message deleted while its marking was written is
not marked, and does not join. A message of a join that the store did not mark is no part of
it and waits like any other. A released input is an input waiting on the place, so under
ADR-0332 §3:3's fourth condition no later input joins past it, and the place's messages are
still understood in the order they arrived.

### 3. Every route out of running settles it first

A pending join is **settled** once it is confirmed or released.

> **Normative.** An activation commits, is taken over, ends, and has its episode frozen
> only once every join it has taken is settled. Each route in this section waits for that,
> and none passes a pending join.

> **Normative.** **Acting's commitment step** (ADR-0332 §3:5) first waits until no join of
> the activation is pending. The step's check and mark then follow, with no await between
> the wait's end and the check.

> **Normative.** **A takeover** (ADR-0332 §4:6) first waits until no join of the named
> activation is pending, inside the taking activation's deadline. ADR-0332 §4:6's one step
> then follows, with no await between the wait's end and that step. Its conditions stand as
> they are, and a pending join refuses no takeover.

> **Normative.** A takeover takes the named activation's whole input as it stands once its
> joins are settled. Each confirmed join is among it, and a released one is not.

> **Normative.** **A stop** sets the stop mark at once (ADR-0295, ADR-0297) and waits for
> nothing. A join taken before the stop belongs to the stopped activation, and that
> activation's end settles it, under §3:6 and §3:7.

> **Normative.** **The controller**, after each stage and before it reads its rules for
> what is due next, waits until no join of the activation is pending, with no await between
> the wait's end and that reading. So `not_understood` reads a join confirmed meanwhile
> (ADR-0332 §3:9), and no end entry the controller appends after a stage passes a pending
> join: not for a silent end, a failed or timed-out stage, a repeated stage, or the stop
> mark.

> **Normative.** **The episode's freeze**, on every ending of the activation (done,
> stopped, failed, or cancelled by a shutdown), first waits until no join of the activation
> is pending. So the routes on which no stage follows the join, such as a stop read before
> the next stage or an interruption, settle it there.

> **Normative.** **A shutdown's cancellation** of an activation is held until the freeze has
> run, and is then raised where the activation's work had stopped.

A failure of the pass ends through the controller's rules where a stage failed, and through
the freeze in every case, so it settles a pending join on both routes. A join released on
any route leaves its input waiting, to be taken in when the activation ends (ADR-0332 §2:4).

### 4. The bounds

> **Normative.** Each wait in §3 is for the reader's one marking write of the pending join,
> and for nothing else. The reader begins that write once it has taken the join, and carries
> it to its end through a cancellation, so that what the store marked is known when the join
> is settled.

> **Normative.** Inside a stage, the wait is also bounded by the pass's deadline (ADR-0332
> §3:14). Where the commitment step's wait reaches the deadline, or the deadline has passed
> when the wait ends, acting dispatches none of the round's calls and not its message. It
> ends as a stage whose deadline expired during it (ADR-0280 §5:1).

> **Normative.** Where a takeover's wait reaches the taking activation's deadline, nothing
> is taken over, and the takeover stage ends as a stage whose deadline expired during it
> (ADR-0280 §5:1).

The controller's wait after a stage and the freeze's are outside any stage, so the one
marking write bounds them. The stage after the controller's wait meets the deadline itself,
under ADR-0280 §5:1. A join does not extend the deadline (ADR-0332 §3:14), and neither does
waiting for one.

### 5. What this decision does not decide

| Not decided here | Where it goes |
| --- | --- |
| The message a joined reply quotes | [#3302](https://github.com/leonapivato/ai-assistant/issues/3302) |
| Recall run again per understanding version | [#3268](https://github.com/leonapivato/ai-assistant/issues/3268), as ADR-0332 §9 places it |
| A durable store of pending input on the line | [#3267](https://github.com/leonapivato/ai-assistant/issues/3267), as ADR-0332 §9 places it |

### 6. Relationship to earlier decisions

Superseded in part; every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0332 | §3:5, in the addition alone: the commitment step first waits until no join is pending, inside the pass's deadline, and a wait that reaches it dispatches nothing and ends acting as an expiry; §3:6, in the addition alone: the appended input is a pending join, counted toward `join_limit` and read by nothing until confirmed; §3:18, in the addition alone: the marking settles the pending join, confirming it for exactly the messages the store marked or releasing it where it marked none; §4:6, in the addition alone: the takeover first waits until no join of the named activation is pending, inside the taker's deadline | §2:1–§2:6, §3:1–§3:8, §4:1–§4:3 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0332 §3:3, §6:5 | Nothing in their words: a pending join is a join taken (§2:2), and `join_limit` is as it stands |
| ADR-0332 §2:4, §3:4 | Nothing: a released input waits as an input that did not join does |
| ADR-0332 §3:7, §3:8 | Nothing: a round a confirmed join sets aside dispatches nothing, and what was dispatched before the join finishes |
| ADR-0332 §3:9, §3:10, §3:16, §4:1 | Nothing in their words: each reads the activation's input, which a pending join is not part of until confirmed (§2:3) |
| ADR-0332 §3:14 | Nothing: a join does not extend the deadline, and the wait inside a stage is bounded by it (§4:2) |
| ADR-0332 §4:7, §4:8 | Nothing: a taken-over activation is stopped as before, and one that committed, was stopped or ended is not taken over |
| ADR-0332 §7 | Nothing: `JoinedInput` and the episode's `joined` keep their shapes, and a pending join is recorded on neither until confirmed |
| ADR-0280 §5:1–§5:3 | Nothing: a stage whose deadline expires during it times out, the fixed defaults end the pass, and the interruption's end entry is appended before the cancellation propagates, which §3:8 then holds until the freeze has run |
| ADR-0293 §6:8, §6:9; ADR-0323 §5:8, §5:10 | Nothing: a message is marked taken in at admission as before, a joined message's marking is ADR-0332 §3:18's as amended here, and after a restart a message a join's marking marked is one an interrupted activation already took in |
| ADR-0295 §§2–4, ADR-0297 | Nothing: a stop is immediate, and the stop mark is read and set as before (§3:5) |

> **Normative.** This decision records its replacements on ADR-0332's status line and in a
> dated header note there, atomically with this ADR under ADR-0070 and ADR-0082, preserving
> its ratified body. The replacements take effect on this ADR's ratification.

## Consequences

**Easier.** A joined message is never acted on before the reader's bookkeeping holds it,
and the episode records every message the reader marked taken in by its activation, as at
admission. A restart neither replays a joined message nor loses one. Each route out of
running is named here, so a review of the implementation reads it against a list rather than
finding the routes one at a time.

**Harder.** Every route out of running waits for a pending join, for at most one marking
write. A commitment step or a takeover that waits past the deadline costs the pass. A
shutdown is held by one marking write for each activation with a pending join.

**The cut, for the dispatcher.** No new lane. The implementation is ADR-0332 step 3's own
pull request, #3294, whose next review round reads it against this text.

**Revisit when** a reader's marking becomes more than one store write, or the line gains a
durable store of pending input (#3267). Either changes what bounds each wait.

## Alternatives considered

- **Join first, then mark** (ADR-0332 §3:6 read alone). Rejected: between the append and
  the marking, the joined message exists only in memory, and #3294's rounds 1 and 2 found a
  replay after a restart, a confirmation before the episode recorded the message, and a
  skipped `/stop`.
- **Mark first, then join, with an in-memory retake.** Rejected: the retake is lost on a
  restart (#3294's round 3).
- **A pending join refuses a takeover.** Rejected: ADR-0332 §4:6's conditions are
  exhaustive, and a join a moment from landing would refuse a person's continuation on
  another place.
- **Settle only before the freeze.** Rejected: a join landing during a silent end or a
  failed stage would be recorded on the episode but never understood, and the failure's
  message written before it.
- **Leave the waits unbounded by the deadline.** Rejected: a marking that crossed the
  deadline and then failed would let the round dispatch after the activation's deadline.
