# 307. A planning round is one model response that writes its own message, keeps episode notes, and names what it was shown by label

- Status: Partially superseded by ADR-0312 (§6:4's *episode notes are absent*, and §4:4's placement, each for the activation's own episode notes shown to its own planning and ADR-0315 (§8:1 whole, and the mark asking for another round wherever §2:1, §2:2, §2:7, §3:4, §8:3 and §10 name it: a round that made a call other than a tidy-up brings another; and §5:3's *a refused call brings a round*, for a tidy-up alone) and ADR-0317 (§3:7, in the addition alone: a stage's failure that ends the activation also writes *couldn't finish*, whatever earlier rounds wrote) and ADR-0321 (§5:1 and §6:1, in the additions alone: the approved-action label; §9:4 whole) and ADR-0338 (§6:1, in the addition alone: the person block, with the current time given in the person's zone) and ADR-0350 (§3:1, §3:7 and §3:8, for an activation the Task Scheduler starts; §5:1, §5:6 and §6:1, each in the addition alone: the scheduled-task and place labels, and the place list) and ADR-0349 (§6:1 and §6:6, each in the addition alone: planning is given absorbed findings, the offers open to it and what it waited on, read fresh each round, and may look up a running activation's findings) and ADR-0356 (§9:2, for the work's own relayed stimulus alone; §2:6, whole: one continuing exchange; §3:1, §3:2 and §3:8, whole: a round's text is its notes, written into no place; §3:4 and §3:5, in their subject alone; §4:1's *as part of its response*; §6:1, in how it is given; §10's `ToolCallingCompleter`, `RoundResponse` and `PlanningRound` rows)
- Date: 2026-10-11
- Scope: the phases after understanding ([#2723](https://github.com/leonapivato/ai-assistant/pull/2723)), milestone M43 ([#2815](https://github.com/leonapivato/ai-assistant/issues/2815)), the second of their four decisions: what a planning round is, the message and the report, episode notes, labels, what planning is given and may look up, the tidy-up call, when rounds run and end, and that planning always runs after understanding. ADR-0306 decided capabilities, authorizing and acting; the digesting decision and the cutover decision are the other two.
- Dependency: [ADR-0306](0306-a-capability-declares-what-its-calls-do-every-call-is-checked-by-rule-and-acting-claims-and-records-what-it-does.md), Accepted and merged at `bff6e259`; the story store, summaries, notes and views ADR-0300, ADR-0303, ADR-0304 and ADR-0305 decide, implemented at `5166d5bc`.
- Authorization: the owner accepted proposal #2723 on 2026-10-11 and, the same day, ruled this decision's content in a pass over it. The dispatcher assigned 0307. This ADR is the proposal's §2 and §3 converted under `docs/proposals/README.md` → "When it is decided". Those rulings authorize ratifying it once its reviews are green, for as long as it settles only what they leave open.
- **Changes `core`, so it is a contract-surface decision.** `core/protocols.py` gains a sibling of `ModelProvider` for a native tool-calling response, and `StoryStore.move` and `StoryStore.split` refuse a planning call whole where a named note is not held; `EpisodeProcessingRecord` gains the rounds and the labels, appended as the episode is extended; ADR-0306's `ActivationEffect` gains the round it claims for; `ControllerStage`, `ControllerRule` and `StoryRefusalReason` gain members; six types are new. `EpisodeProcessingRecord` crosses the wire, so `PROTOCOL_VERSION` advances (§10).
- **Partially supersedes**, each for an activation the phases plan (§1:3), except where a scope below says otherwise:
  [ADR-0170](0170-a-reply-is-not-a-tool-the-turn-composes-its-answer-and-the-outcome-carries-it.md) (whole: the reply is planning's own text, and no compose stage runs);
  [ADR-0226](0226-the-planner-names-one-more-read-beside-its-plan-and-the-loop-services-it-into-the-supply.md), [ADR-0228](0228-a-serviced-read-may-revise-the-plan-once-and-the-turn-stops-looking-at-a-bound-or-a-deadline.md) and [ADR-0251](0251-an-attempt-investigates-in-bounded-rounds-over-typed-read-outcomes-and-keeps-a-reserve-to-answer-with.md) (each whole: planning's rounds replace the turn loop's read rounds);
  [ADR-0280](0280-an-activation-controller-runs-the-stages-by-rules-and-records-every-choice-with-the-episode.md) (§4:1–§4:2's enums, in the additions alone; §4:6's loop guard, for the planning stage alone);
  [ADR-0286](0286-an-episode-is-open-while-its-activation-runs-and-frozen-when-it-ends.md) (§3:3's admitted differences, in the additions alone; §3:8's *no field is added for a stage's result*, for planning's rounds and labels alone);
  [ADR-0293](0293-the-hubs-chat-is-a-hosted-medium-and-a-conversation-keeps-its-own-transcript.md) (§6:14 and §11:6, each whole; §6:10, §6:11 and §10:4, until the timers and proactivity milestone);
  [ADR-0303](0303-a-storys-page-is-free-notes-rewritten-whole-and-the-place-window-links-each-item-to-its-activation.md) (§6:2's *passed over*, for a split or move whose actor is planning);
  [ADR-0304](0304-a-storys-page-is-its-summary-shown-where-owner-records-are-a-lookalike-is-not-read-and-a-story-is-a-referent.md) (§9:3's and §9:5's treatment of a named note the story does not hold, for a move whose actor is planning);
  [ADR-0306](0306-a-capability-declares-what-its-calls-do-every-call-is-checked-by-rule-and-acting-claims-and-records-what-it-does.md) (§6:1's `ActivationEffect`, in the addition alone).
- Recorded: 2026-10-11 — §10's `project_episode` row also partially supersedes
  [ADR-0284](0284-an-episode-is-the-experience-of-processing-its-activation.md) §8:1's
  projection, in the addition alone: it renders an episode's round messages and episode
  notes, under the reader's audience. The header above did not name it when this ADR merged
  ([#2835](https://github.com/leonapivato/ai-assistant/issues/2835)); this note records the
  decision §10 made and alters none, and ADR-0284's status line and a dated note there now
  carry it.
- Partially superseded: 2026-10-11 by ADR-0312 — two scopes, one rule. §6:4's *episode
  notes are absent*, and §4:4's placement, each for the activation's own episode notes
  shown to its own planning: an activation's own rounds, their episode notes and its own
  digests' evidence are shown to its own planning on every pass. §6:4 governs, as written,
  what planning is shown of other episodes and stories, and §4:4's placement governs every
  other reader. Every other clause stands. This scoped
  replacement takes effect on ratification of ADR-0312. This reciprocal header record
  accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the
  ratified body below are preserved.
- Partially superseded: 2026-10-13 by ADR-0315 — §8:1 whole: a new round runs once
  every call of the previous round has finished, digests included and a tidy-up
  excepted, whenever that round made at least one call other than a tidy-up, whatever its
  calls brought back. The mark asking for another round retires: a round has three parts
  (§2:1), the notes alone ride the response (§2:2, §2:7), the round after a call in the
  world reports it with no mark (§3:4's second sentence), §8:3 reads without *whatever its
  mark*, and §10's `RoundResponse` and `PlanningRound` rows lose `another_round`. §5:3's
  *a refused call brings a round* no longer reaches a tidy-up, which brings none. Every
  other clause stands. This scoped replacement takes effect on ratification of ADR-0315.
  This reciprocal header record accompanies the numbered draft under ADR-0070 and
  ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-13 by ADR-0317 — one scope. §3:7, in the addition alone:
  a stage's failure that ends the activation, the controller's loop guard among them,
  also writes the fixed *couldn't finish* message, whatever earlier rounds wrote, as the
  round limit and a deadline do; the message is the one ADR-0317 §3:1 describes, since ADR-0317 replaces
  ADR-0293 §9:1 (ADR-0317 §3:3). Every other clause stands. This scoped replacement takes
  effect on ratification of ADR-0317. This reciprocal header record accompanies the
  numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body
  below are preserved.
- Partially superseded: 2026-10-15 by ADR-0321 — §5:1 and §6:1, in the additions alone: planning is shown its activation's approved actions under a label of a new kind (ADR-0321 §4:2). §9:4 whole: a call that needs the user is asked about, not answered *it cannot be done yet* (ADR-0321 §2). §3:6 stands, and so does every other clause. This replacement takes effect on ratification of ADR-0321. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-21 by ADR-0338 — §6:1, in the addition alone: planning is also given the person block's five profile fields, its kept-in-mind slot and the person's pending suggestions, and the current time is given in the person's zone (ADR-0338 §3:6, §7:3). Every other clause stands. This replacement takes effect on ratification of ADR-0338. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-25 by ADR-0350 — §3:1, §3:7 and §3:8, for an activation the Task Scheduler starts: each reads the places on its place list in place of the place its input came from, and §3:7's *couldn't finish* goes into the suggested places on that list (ADR-0350 §6:7). §5:1, in the addition alone: planning names scheduled tasks by the label kind `T` and places by the label kind `L` (ADR-0350 §5:13); §5:6, in the addition alone: a place-window item that links to a scheduled task is shown with that task's label beside its episode label (ADR-0350 §9:2); §6:1, in the addition alone: planning in an activation offered spawn is given its place list, places grouped under channel headings that are never named, built when shown, with no place put on it by where a task was set (ADR-0350 §5:10–§5:12). Every other clause stands. This replacement takes effect on ratification of ADR-0350. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-25 by ADR-0349 — §6:1 and §6:6, each in the addition alone: planning is given, read fresh at every round, each absorbed activation's finished findings, the offers open to it, and the finished work of each activation it waited on, and may look up a running activation's findings (ADR-0349 §6:1, §7:10, §7:19, §7:27). Every other clause stands. This replacement takes effect on ratification of ADR-0349. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-30 by ADR-0356 — §9:2, for the work's own relayed stimulus alone, by the owner's ruling on #3515: its words are shown to its planning, marked relayed, while a forward and every other outside content stay withheld (ADR-0356 §3:7). §2:6, whole: each round is asked with the work's whole exchange, appended to and never re-rendered, with what changed arriving as news (ADR-0356 §5:1). §3:1, §3:2 and §3:8, whole: a round's text is planning's reply to the system, kept as its notes and written into no place; what people receive comes only from message calls (ADR-0356 §7:2, §7:3). §3:4 and §3:5, in their subject alone: what they say of a round's text as a message holds of its message calls, as the tools decision decides. §4:1's *as part of its response*: the notes are the response's text. §6:1, in how it is given: earlier rounds, acting's outcomes and digested evidence reach planning through the exchange, and the rest is laid out as ADR-0356 §3 has it. §10's `ToolCallingCompleter`, `RoundResponse` and `PlanningRound` rows, as ADR-0356 §13 states them. Every other clause stands. This replacement takes effect on ratification of ADR-0356. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.

## Context

**The proposal.** #2723 sets out how an activation goes from understood to done. ADR-0306
decided what a capability declares, how authorizing checks each call by rule, and how acting
runs, claims and records calls. This decision is the phase that proposes those calls: one
model response at a time, each a round.

**What is built, at `61fe73e6`.** After understanding, the old turn loop runs as controller
stages: the planner's read rounds (ADR-0226, ADR-0228, ADR-0251) and a compose stage that
writes the reply (ADR-0170), which an adapter writes into the conversation (ADR-0293 §10:1).
`ModelProvider.complete` takes and returns `Message` values and represents no tool exchange;
every structured model output today is JSON parsed from reply text. The episode record holds
no rounds, messages or notes. The story views planning will read exist in part: the short view
understanding reads, the owner's summary view, and where a matter stands.

**The owner's rulings, 2026-10-11.** Each clause below that records a ruling states it as
ruled. The clauses that settle what the rulings leave open are listed as such in the pull
request.

## Decision

We will have planning answer in rounds, each one model response in the provider's native
tool-calling shape carrying its text, its calls, its episode notes and a mark asking for
another round; write the text into the input's place as soon as the round is recorded; name
everything planning was shown by a label the hub maps to an id; and run a new round only
once every call of the last one has finished and something calls for it.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews
> `CONTRIBUTING.md` → "Finishing an ADR PR" requires have returned green on one tree
> and the owner's authorization to ratify stands; an assigned number or a green review
> alone does not change its status.

> **Normative.** No lane implements this decision until it has merged `Accepted` and the
> cutover decision has merged. Its lanes are cut then, and the first build lane is the
> thin path the cutover decision names.

> **Normative.** Every earlier clause this decision replaces is replaced for an activation
> the phases plan and for no other, except where its header names a wider scope. The old
> turn loop keeps those clauses until the cutover decision removes it.

### 2. A round

> **Normative.** A round is one model response in the provider's native tool-calling
> shape, with four parts: its text, its tool calls, its episode notes, and a mark that
> another round is needed.

> **Normative.** The notes and the mark are part of the response, not calls: neither goes
> through authorizing, and neither brings a round as a call does. What the mark brings is
> §8's.

> **Normative.** Each round is one controller step. It is recorded in the episode, never
> edited, and names the round it follows. Claims point at it by id.

> **Normative.** A round is recorded once the episode writer's append of it has returned
> (ADR-0286 §3:1). An append that fails is a capture failure under ADR-0286 §5, and holds
> back neither the round's message nor its calls (ADR-0286 §3:7).

> **Normative.** A round's calls run in parallel. A call that needs another call's result
> or success goes in a later round, and no call refers to another's output.

> **Normative.** Each round is requested afresh: the instruction and planning's inputs
> (§6), earlier rounds and acting's outcomes among them, are rendered as text, and no
> earlier tool exchange is replayed in the provider's native form.

> **Normative.** How a provider's native shape carries the notes and the mark is the
> `models/` implementation's. Outside `models/` they are parts of the response and never
> calls.

### 3. The message

> **Normative.** A round's text is written into the place the input came from (ADR-0306
> §4:7). It goes out as soon as the round is recorded, without waiting for the round's
> calls, and is claimed and recorded as ADR-0306 §5 decides for a message.

> **Normative.** A round whose text is empty writes no message.

> **Normative.** Planning writes the words itself. There is no compose step and no
> streaming.

> **Normative.** A round's text never claims how its own calls went, and planning's
> instruction says so. When the user will want to hear how a call in the world went,
> planning marks another round, and that round reports it from acting's record. A failure
> or an unknown outcome is always reported.

> **Normative.** The report is the text of a round that runs because the previous round's
> calls finished. It is written from acting's record and claims no more than that record
> shows, and an unknown outcome is reported as unknown.

> **Normative.** Questions and answers are ordinary messages: a question carries no
> options, and an answer names no question.

> **Normative.** When processing cannot finish because the round limit or a deadline ends
> it, the fixed *couldn't finish* message is written into the input's place as ADR-0293
> §9:1 writes it, whatever earlier rounds wrote.

> **Normative.** Where the input's place takes no message, as with an event, the round's
> text is kept in the episode and written nowhere, and planning's instruction tells it so
> up front.

### 4. Episode notes

> **Normative.** Episode notes are free text, optional, with no citations. They are saved
> with their round in its episode and written only by planning, as part of its response.

> **Normative.** They are read wherever the episode is read, whether or not it is in a
> story: by the activation's later rounds, by later activations through the episode window
> or recall, by the tidy-up and by the matters pass (ADR-0303 §5:1, §8:9).

> **Normative.** They are marked as a story's notes are, under ADR-0303 §3:1's rule, and a
> marked one counts as outside content for an activation that reads it (ADR-0303 §3:6,
> ADR-0306 §4:5).

> **Normative.** They are placed for the owner alone, as a story's notes are (ADR-0303
> §3:9, ADR-0304 §4:1).

> **Normative.** They move with their episode. They are never copied onto a story
> (ADR-0300 §10:1); the tidy-up may take what they say into the summary.

> **Normative.** They have no size cap for now.

### 5. Labels

> **Normative.** Planning names things by label: stories S1, S2…, episodes E1…, a story's
> notes N1…, other memory records M1… and results R1…. Each thing gets its label the first
> time planning is shown it, from any source, its own story reads and the story notes it
> writes included, and the label holds for the whole activation. Episode notes take no
> label.

> **Normative.** The hub maps labels to ids, so planning never handles an id. "Any story
> by id" (ADR-0300 §10:2) and "any other story's page" (ADR-0300 §10:7) mean any story
> planning has been shown.

> **Normative.** A call naming a label planning was never shown, or naming a note the
> story it moves from does not hold, is refused whole, with the reason, and runs nothing.
> A refused call brings a round.

> **Normative.** The hub refuses such a call before it is authorized, against what it
> was shown and the stories as they stand then; and the story store refuses a split or a
> move whose actor is planning, inside its transaction, where a note it names is not held
> by the story moved from when it runs, so a note moved away meanwhile, by another call of
> the round or by the matters pass, still refuses the whole call.

> **Normative.** This is how planning names the notes a move or a split carries (ADR-0303
> §9:4).

> **Normative.** A place-window item that links to an activation (ADR-0303 §7:1) is shown
> with that activation's episode label.

> **Normative.** The activation's labels, with the ids they name, are recorded with its
> episode.

### 6. What planning is given and may look up

> **Normative.** Planning is given: understanding's record and its story links; what both
> recall runs found, under the reader rule, each episode with its notes; for each story the
> activation belongs to (ADR-0300 §8), its summary, the notes and episodes newer than it,
> when it was last tidied and how many changes have come since, the short views of the
> stories it is part of marked as inherited, where the matter stands, and its latest
> episodes; the short view of a story understanding cited as a referent that the
> activation is not in; the place window and the episode window; the capability names and
> the channel kind's description (ADR-0292 §8:1); and digested evidence, acting's outcomes,
> earlier rounds and their notes, and the current time.

> **Normative.** Marked records are shown as outside content (ADR-0303 §3:7).

> **Normative.** How many changes have come since a story was last tidied is one count:
> the notes and the episodes pending on it.

> **Normative.** Where a record placed for the owner alone may not be shown, as on a spoken
> pass, planning's views follow understanding's (ADR-0304 §4, ADR-0305 §4): the summary is
> withheld and the view says so; story notes and episode notes are absent, with nothing
> said about them; episodes, and where the matter stands, come only from what the audience
> may be shown; and when the summary was last tidied, and the count of changes since, are
> shown on every pass.

> **Normative.** On such a pass planning can still write notes and change stories, but a
> move or a split it makes there carries members only.

> **Normative.** Planning may look up for itself a memory search, the full view of any
> story it has been shown, and pulls. Raw outside content reaches it only through
> understanding's or a digest's record.

### 7. The tidy-up

> **Normative.** The tidy-up is planning's call, made from when the summary was last
> tidied and how many changes have come since. It never brings a round, even when it
> fails, and its outcome is recorded in the story's version log, not the episode
> (ADR-0300 §10:4). This is ADR-0292 §12:2 as written.

> **Normative.** Neither a next round nor the activation's end waits for a tidy-up; it
> runs to its end as ADR-0306 §3:3 decides, after the activation has ended if need be.

### 8. When rounds run and end

> **Normative.** A new round waits until every call of the previous round has finished,
> digests included and a tidy-up excepted (§7:2). It runs when a call brought a result,
> digested where it carries outside text; when a call failed, came back unknown, needed
> the user or was refused (ADR-0306 §4 and §5:9, and §5:3 of this decision); or when the
> round was marked. Otherwise the activation ends after the round.

> **Normative.** Each digest starts as soon as its result arrives, and a call's deadline
> bounds the wait.

> **Normative.** No progress is a round with no calls. It ends the activation after its
> message, whatever its mark.

> **Normative.** A loop of refused calls is ended by the round limit.

> **Normative.** The round limit, the deadlines and the numbers belong to
> [#2589](https://github.com/leonapivato/ai-assistant/issues/2589). A stop lands after the
> current round (ADR-0297).

> **Normative.** Planning always runs after understanding: its first round runs once
> understanding has recorded and recall's second run, which the digesting decision
> decides, has finished.

### 9. Rules

> **Normative.** Planning proposes and never permits.

> **Normative.** Planning never reads raw outside content.

> **Normative.** Planning never substitutes for what the user asked.

> **Normative.** Planning answers a call that comes back *needs you* plainly: it cannot be
> done yet.

> **Normative.** No citation rule applies in this milestone. The milestone that first
> reads citations, authority or learning, adds them.

### 10. The code it binds

| Code | Change |
| --- | --- |
| `ToolCallingCompleter` | New `core` Protocol, a sibling of `ModelProvider` on ADR-0143 §1's and ADR-0173 §5's ground, with one member: `async def respond(self, messages: Sequence[Message], tools: Sequence[OfferedTool], *, model: str \| None = None) -> RoundResponse`. Implemented in `models/` over pydantic-ai's native tool calling |
| `OfferedTool` | New frozen record: a capability's `name`, `description` and `parameters` (its JSON schema, with ADR-0306 §2:9's added arguments) |
| `ProposedCall` | New frozen record: the provider's `call_id`, the capability `name`, and `arguments` as a JSON object |
| `RoundResponse` | New frozen record: `text`, `calls: tuple[ProposedCall, ...]`, `notes: str \| None` and `another_round: bool` |
| `PlanningRound` | New frozen record: its `id`; `follows`, the round before it or `None`; `recorded_at`; the four parts of its `RoundResponse`; and `notes_marked: bool` |
| `PlanningLabel`, `LabelKind` | New frozen record: `label`, `kind: LabelKind` and the `id` it names; and a new closed enumeration: `story`, `episode`, `note`, `memory`, `result` |
| `EpisodeProcessingRecord` | Gains `rounds: tuple[PlanningRound, ...]` and `labels: tuple[PlanningLabel, ...]`, both empty by default; `schema_version` advances by one |
| `core: episode_extends` | Also admits entries appended at the end of `rounds` and of `labels`, every earlier entry unchanged (ADR-0286 §3:2–§3:3) |
| `EpisodicMemory.outcome` | Set once, in the revision that freezes the episode, to the activation's messages in the order written, joined by a blank line, or left `None` where it wrote none (ADR-0284 §4:1, ADR-0286 §3:3) |
| `ActivationEffect` (ADR-0306 §6) | Gains `round: DurableIdentifier \| None`, the round whose call or message it claims, `None` only on the *couldn't finish* message |
| `ControllerStage`, `ControllerRule` | Gain `planning`; and `first_round_due`, `round_due` and `round_limit_reached`, answering as §8 states |
| `StoryStore.move`, `StoryStore.split`, `StoryRefusalReason` | Where `actor` is `planning`, a named note the story moved from does not hold refuses the whole operation `note_not_held`, writing nothing (§5:4); `StoryRefusalReason` gains `note_not_held`. No signature changes |
| `core/episode_encoding.py: project_episode` | Renders an episode's round messages and episode notes, under the reader's audience (§6:4) |
| `ModelProvider`, `Message` | Unchanged |
| Planning's story view | Assembled in `orchestration` from `StorySummaryState`, `ShortView`, `StoryStanding` and the version log; no `core` type |
| The message write | `ChatWriter.send` over `ConversationStore.append_message`, under ADR-0306 §5's claim |

> **Normative.** The Protocol and the new types the table names land as one Protocol triad,
> with the conformance suite and the canonical fake, in the lane that builds the planning
> round; `ActivationEffect.round` lands with ADR-0306 §6:1's triad; and the `StoryStore`
> refusal lands with its conformance coverage and the canonical fake's in the lane that
> builds planning's story calls.

> **Normative.** Where the planning rule rows sit in the table the controller is switched
> to is the cutover decision's; their members and what each answers are §8's.

> **Normative.** The change that adds the rounds and the labels to
> `EpisodeProcessingRecord` advances `PROTOCOL_VERSION`, on ADR-0124 §9's rule, as does any
> change here to another shape the wire carries.

### 11. Relationship to earlier decisions

| Earlier decision | What changes |
| --- | --- |
| ADR-0170 | Whole, for an activation the phases plan: the reply is planning's own text, written by the round (§3), and no compose stage runs |
| ADR-0226, ADR-0228, ADR-0251 | Each whole, for an activation the phases plan: planning's rounds (§2, §8) replace the turn loop's read rounds, revisions and allowance |
| ADR-0280 §4:1–§4:2 | The enums gain the members §10 names, in the additions alone |
| ADR-0280 §4:6 | The loop guard, for the planning stage alone: it runs once per round, bounded by the round limit and ended by a round with no calls (§8), as §4:6 foresaw |
| ADR-0284 §4:1 | Nothing: `outcome` is still the text the activation sent back, its several messages joined |
| ADR-0286 §3:3, §3:8 | §3:3's admitted differences gain entries appended at the end of `rounds` and `labels`, in the additions alone; §3:8's *no field is added for a stage's result*, for planning's rounds and labels alone. `outcome` takes its value once, as §3:3 already admits |
| ADR-0292 §12:2 | Nothing: the tidy-up is planning's choice as written (§7) |
| ADR-0293 §6:10, §6:11, §10:4 | Until the timers and proactivity milestone: a message goes only into the input's place, no activation whose place takes no message writes one, and the assistant starts no conversation |
| ADR-0293 §6:14 | Whole: questions and answers are ordinary messages (§3:6) |
| ADR-0293 §9:1 | Nothing: §3:7 writes it also where the round limit or a deadline ends the activation after earlier messages |
| ADR-0293 §11:6 | Whole: its condition never holds now that question messages are dropped; `answer` retires as the cutover decision decides |
| ADR-0300 §10; ADR-0303 §5:1, §8:9, §9:4 | Nothing: §4 gives episodes the notes, and §5 the labels, these clauses wait for |
| ADR-0303 §6:2; ADR-0304 §9:3, §9:5 | For a split or move whose actor is planning, a named note the story does not hold refuses the whole operation instead of being passed over (§5:4); for every other actor they stand |
| ADR-0306 §6:1 | `ActivationEffect` gains `round`, in the addition alone |

> **Normative.** This numbered draft records its replacements on the status lines and in
> a dated header note of ADR-0170, ADR-0226, ADR-0228, ADR-0251, ADR-0280, ADR-0286,
> ADR-0293, ADR-0303, ADR-0304 and ADR-0306, atomically with this ADR under ADR-0070 and
> ADR-0082, preserving their ratified bodies. The replacements take effect on this ADR's
> ratification.

## Consequences

**What becomes possible.**
- A quick question is answered in one planning round, and a task whose second call needs
  the first's result works across rounds.
- The user hears what is being done at once and how it went from acting's record, never a
  guess written beside the call.
- What planning thought about an activation is kept and read later, without being copied
  onto a story.
- Planning never handles an id, so a call cannot name something it was not shown.

**What it costs.**
- A report costs another round.
- Every model that runs planning must support native tool calling.
- Episode notes grow with no cap until the test hub shows whether they need one.

**What stays open.**
- The numbers ([#2589](https://github.com/leonapivato/ai-assistant/issues/2589)).
- Streaming, and writing into other places
  ([#2590](https://github.com/leonapivato/ai-assistant/issues/2590)).
- Citations, for the milestone that first reads them.
- An episode-notes cap.

## Alternatives considered

- **Kinds of step** (read, act, inside action, message). Rejected: every difference between
  them is a property of the capability called, and native tool calls express a plan more
  reliably than a custom schema.
- **Planning's intents, turned into calls by the hub.** Rejected: a second judgment, and
  authorizing would check something planning never said.
- **A separate writing step, so replies stream.** Not now: streaming is not needed, and a
  writer can be added later without changing a round's shape.
- **A separate closing phase.** Folded into planning's last round.
- **The tidy-up added by rule.** Replaced by planning's own call, given how far behind each
  summary is.
- **Every round after calls bringing another round.** Rejected: a round that only writes a
  note would bring a second planning call with nothing to plan from.
- **A round on each result as it arrives.** Rejected: planning would plan from half the
  picture, and rounds would overlap running calls.
- **The hub holding a round's message until its calls finish.** Rejected: a marked round
  reports the outcome with no new rule.
- **Dropping a wrong label and writing the rest, as the matters pass does.** Rejected for
  planning: it has a next round to fix the call, and a partial move is one it believes
  whole.
- **Hiding the tidy-up's facts where owner-only records may not be shown.** Rejected: a
  matter handled only by voice would never be tidied.
- **Planning citing what it relies on, now.** Dropped: nothing reads citations until a
  later milestone.
- **Widening `ModelProvider` with a tool-calling member.** Rejected: a member there asserts
  of every route a capability not every model offers, as ADR-0143 §1 and ADR-0173 §5 found
  for batches and streaming.
