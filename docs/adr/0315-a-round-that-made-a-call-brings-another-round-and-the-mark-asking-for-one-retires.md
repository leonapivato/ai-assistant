# 315. A round that made a call brings another round, and the mark asking for one retires

- Status: Partially superseded by ADR-0321 (§3:1 and §5's `RoundResponse`, `PlanningRound` and pydantic-ai completer rows, in the additions alone: the calls a round's message asks about) and ADR-0349 (§2:1–§2:3, each in the addition alone: a waiting round never ends its activation, and a round held back for an offer brings another) and ADR-0356 (§3:1, §3:2 and §3:3, whole: a round has two parts and no tool is reserved; §4:2, in its subject alone; §4:3, in its tidy-up exception alone; §5's `RoundResponse`, `ToolCallingCompleter` and pydantic-ai completer rows)
- Date: 2026-10-13
- Scope: the phases, milestone M43 ([#2815](https://github.com/leonapivato/ai-assistant/issues/2815)): when planning's next round runs. It corrects [ADR-0307](0307-a-planning-round-is-one-model-response-that-writes-its-own-message-keeps-episode-notes-and-names-what-it-was-shown-by-label.md) §8:1 after planning was measured dropping the later part of its own plan ([#2892](https://github.com/leonapivato/ai-assistant/issues/2892)).
- Authorization: the owner ruled this decision's content on 2026-10-13. The dispatcher assigned 0315 and authorized ratifying it once its reviews are green.
- **Changes `core`, so it is a contract-surface decision.** `RoundResponse` and `PlanningRound` lose `another_round`, and `EpisodeProcessingRecord.schema_version` advances. `PlanningRound` crosses the wire inside `EpisodicMemory.processing_record`, so `PROTOCOL_VERSION` advances; `RoundResponse` does not cross it. `ToolCallingCompleter`'s signature is unchanged (§5).
- **Partially supersedes**
  [ADR-0307](0307-a-planning-round-is-one-model-response-that-writes-its-own-message-keeps-episode-notes-and-names-what-it-was-shown-by-label.md):
  §8:1 whole; §2:1's fourth part, the mark; §2:2's and §2:7's mark; §3:4's *planning marks
  another round*; §5:3's *a refused call brings a round*, for a tidy-up alone; §8:3's
  *whatever its mark*; and §10's `RoundResponse` and `PlanningRound` rows, in the mark alone.
- Partially superseded: 2026-10-15 by ADR-0321 — §3:1 and §5's `RoundResponse`, `PlanningRound` and pydantic-ai completer rows, in the additions alone: a response also names the calls its message asks about, the round records them, and the completer's reserved tool carries the naming beside the notes (ADR-0321 §2:3, §2:8). Every other clause stands. This replacement takes effect on ratification of ADR-0321. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-25 by ADR-0349 — §2:1–§2:3, each in the addition alone: the first round of an activation that waits on an older one is a waiting round, which never ends the activation, whether it made a call, only tidy-ups or none, and the round after it runs once each activation it waits on has ended; and a round whose acts were held back because an offer was open that the round was not shown brings another round, whatever it called (ADR-0349 §7:14, §7:26). Every other clause stands. This replacement takes effect on ratification of ADR-0349. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-30 by ADR-0356 — §3:1, §3:2 and §3:3, whole: a round has two parts, its text, which is its notes, and its calls, and no tool carries the notes or is reserved (ADR-0356 §7:1, §7:4). §4:2, in its subject alone: a round writes a message only by a message call. §4:3, in its tidy-up exception alone: the tidy-up's description says it brings no round (ADR-0356 §10:4). §5's `RoundResponse`, `ToolCallingCompleter` and pydantic-ai completer rows, as ADR-0356 §13 states them. Every other clause stands. This replacement takes effect on ratification of ADR-0356. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.

## Context

**The rule being replaced.** ADR-0307 §8:1 runs a new round when a call of the last one
brought a result, failed, came back unknown, needed the user or was refused, or when
planning marked the round. A call that succeeds and brings nothing back, such as a note on
a story, brings a round only if planning asks for one.

**What was measured.** The M43 QA run found planning deciding, in its thinking, to do part
of a request in a later round and then not asking for one, so that part was never done
(#2892). A live probe against `claude-opus-4-8` with thinking on (PR #2897, closed) found:

- planning dropped the later part of a two-step sequence in 21 of 48 rounds;
- every dropped round made exactly one call and stopped, as a model trained to wait for a
  tool's result would;
- eight instruction wordings could not cut the drops without raising claims in the text
  that a call went (ADR-0307 §3:4); the best, with a change to the reserved tool's description,
  still dropped about one round in five.

[#2864](https://github.com/leonapivato/ai-assistant/issues/2864) had the same shape: a
`remember` round that wrote nothing and asked for nothing.

**The owner's framing.** Rounds, notes and the tidy-up are the assistant's own
housekeeping. The user asks for outcomes, and planning follows through on its own plan
without having to remember to ask for a round. ADR-0307 rejected "every round after calls
bringing another round" because a round that only writes a note would bring a planning call
with nothing to plan from. The measurement shows that call is cheaper than the drops.

## Decision

We will run a new round after every round that made a call other than a tidy-up, once its
calls have finished, and retire the mark that asked for one.

### 1. Status and delivery

> **Normative.** This document remains `Proposed` until the reviews
> `CONTRIBUTING.md` → "Finishing an ADR PR" requires have returned green on one tree
> and the owner's ruling and the dispatcher's authorization to ratify stand.

> **Normative.** No lane implements this decision until it has merged `Accepted`.

> **Normative.** One lane implements it: the controller's round rule, the mark's removal
> from the `ToolCallingCompleter` triad (`RoundResponse`, its canonical fake, its
> conformance suite and the pydantic-ai completer) and from `PlanningRound`, planning's
> instruction, and a live re-measurement of #2892's scenarios on the probe PR #2897
> describes, with the drop rate and the ADR-0307 §3:4 claim rate reported in its pull request.

### 2. When a round brings another

> **Normative.** A new round runs once every call of the previous round has finished,
> digests included and a tidy-up excepted (ADR-0307 §7:2), whenever that round made at
> least one call other than a tidy-up, whatever its calls brought back. This replaces
> ADR-0307 §8:1.

> **Normative.** A tidy-up never brings a round, whatever came of it, a refusal included
> (ADR-0307 §7:1). A round whose only calls are tidy-ups, like a round with no calls, ends
> the activation after its message.

> **Normative.** No progress is a round with no calls, and it ends the activation after its
> message (ADR-0307 §8:3, which stands without *whatever its mark*).

> **Normative.** The round limit ends every loop of rounds this section makes, as it ends a
> loop of refused calls (ADR-0307 §8:4), and its numbers stay
> [#2589](https://github.com/leonapivato/ai-assistant/issues/2589)'s (ADR-0307 §8:5).

### 3. A round's parts

> **Normative.** A round is one model response in the provider's native tool-calling
> shape, with three parts: its text, its tool calls and its episode notes. This replaces
> ADR-0307 §2:1.

> **Normative.** The notes are part of the response, not a call: they go through no
> authorizing and bring no round. This replaces ADR-0307 §2:2.

> **Normative.** How a provider's native shape carries the notes is the `models/`
> implementation's. Outside `models/` they are a part of the response and never a call.
> This replaces ADR-0307 §2:7.

> **Normative.** No part of a response asks for a round or holds one back; §2 alone decides
> whether one runs.

### 4. The report

> **Normative.** When the user will want to hear how a call in the world went, the round
> §2 brings after it reports it from acting's record. This replaces ADR-0307 §3:4's second
> sentence; its first and third stand, so the text never claims how its own calls went, and
> a failure or an unknown outcome is always reported.

> **Normative.** A round that has nothing the user will want to hear writes no message
> (ADR-0307 §3:2).

> **Normative.** Planning's instruction tells it that a round with a call other than a
> tidy-up is followed by another once its calls finish, and that a round with no calls ends
> the activation.

### 5. The code it binds

| Code | Change |
| --- | --- |
| `RoundResponse` | Loses `another_round`: `text`, `calls` and `notes` |
| `PlanningRound` | Loses `another_round`: its `id`, `follows`, `recorded_at`, the three parts of its `RoundResponse`, and `notes_marked` |
| `EpisodeProcessingRecord` | `schema_version` advances by one, and the memory store's episode format marker with it, on ADR-0308 §7:3's terms: no record stored before it is read |
| `ToolCallingCompleter` | Signature unchanged; its canonical fake and conformance suite lose the mark |
| The pydantic-ai completer | Its reserved tool carries the notes alone (§3:3) |
| `ControllerRule` | Unchanged members; `round_due` and `round_limit_reached` answer as §2 states, through ADR-0309 §3's rows 11 and 12 |
| Planning's instruction and its rendering of earlier rounds | Neither names a mark (§4:3) |

> **Normative.** The change that removes `another_round` from `PlanningRound` advances
> `PROTOCOL_VERSION` on ADR-0124 §9's rule, since `PlanningRound` is carried inside the
> wire-carried `EpisodicMemory.processing_record`.

### 6. Relationship to earlier decisions

| Earlier decision | What changes |
| --- | --- |
| ADR-0307 §8:1 | Whole: §2:1 replaces it |
| ADR-0307 §2:1, §2:2, §2:7 | The mark leaves; §3 restates each for three parts |
| ADR-0307 §3:4 | Its second sentence: the round §2 brings reports, with no mark (§4:1) |
| ADR-0307 §3:5 | Nothing: the report is still the text of a round run because the previous round's calls finished |
| ADR-0307 §5:3 | *A refused call brings a round*, for a tidy-up alone: it brings none (§2:2); every other refused call brings one under §2:1 |
| ADR-0307 §7 | Nothing: §2:2 holds it as written |
| ADR-0307 §8:3 | *Whatever its mark* names nothing; the rule stands (§2:3) |
| ADR-0307 §8:2, §8:4–§8:6 | Nothing |
| ADR-0307 §10 | The `RoundResponse` and `PlanningRound` rows, in the mark alone (§5) |
| ADR-0309 §3 | Nothing: rows 8, 11 and 12 answer as ADR-0307 §8 states, which now reads with §2 |
| ADR-0312, ADR-0314 | Nothing: neither names the mark |

> **Normative.** This numbered draft records its replacements on ADR-0307's status line and
> in a dated header note there, atomically with this ADR under ADR-0070 and ADR-0082,
> preserving its ratified body. The replacements take effect on this ADR's ratification.

## Consequences

**What becomes possible.**
- Planning's plan for later is carried out without planning having to ask: a note then a
  tidy-up, or a split then a note on the new story, runs across two rounds.
- The round after a stored fact sees that it was stored, so it can say so truthfully.

**What it costs.**
- One more planning call after a round whose calls bring nothing back. The round's message
  has already gone out, so the user is not kept waiting for it, but the activation ends
  that much later, and an input that arrives meanwhile is taken up that much later too.

**What stays open.**
- The numbers ([#2589](https://github.com/leonapivato/ai-assistant/issues/2589)).

## Alternatives considered

- **A better instruction.** Rejected: eight wordings were measured, and each that cut the
  drops raised claims in the text that a call went (#2897).
- **The instruction and the reserved tool's description together.** Rejected: still about
  one dropped round in five, and the claims stayed at today's rate (#2897).
- **A mark that ends the loop instead of one that continues it.** Rejected: it still asks
  planning to remember a step of the assistant's own housekeeping, and a round with no
  calls already ends the activation.
