# 356. The system briefs planning in one continuing exchange, planning's text is its notes, and an episode is shown by its short view

- Status: Partially superseded by ADR-0357 (§3:2's table, its situation row, in the addition alone: the place list, each place with its `L` label) and ADR-0359 (§5:5, in the addition alone: a matter changed and a memory forgotten since the work was shown them) and ADR-0360 (§5:5, in the addition alone: the time, other works started or ended, and pins and fields the person changed, since the work was shown them) and ADR-0361 (§7:7 and §7:10, each in the addition alone: a taken input's place, and an approval's activation's place list) and ADR-0364 (§3:1's sections and §3:2's table, in the additions: Connections, and the situation's row; §3:3, in planning's briefing alone: `where` and `from`; §7:7 and §7:10's second sentence; §10:1's text, for this version; §10:2's list, in the addition alone; §10:6's second sentence)
- Date: 2026-10-30
- Scope: planning's exchange with its model. The system briefs planning (§2) with tagged text in a fixed order, the stimulus first (§3). Every section is always present, every tool is offered on every round, and the instruction takes no flag (§4). A work's rounds are one continuing exchange, appended to and never re-rendered, with what changed arriving as news (§5), and a provider's own response, its thinking included, is handed back to it (§6). Planning's text is its reply to the system, kept as its notes and written to no one, and a message is a call, checked, claimed and recorded as the round's message was (§7). The episode records one entry for each call (§8), and other work sees an episode through its short view (§9). The instruction and its required wording (§10), how it is judged (§11), understanding's two phrases (§12), the code it binds (§13) and the lanes (§14). This is the first of three decisions converted from proposal [#3526](https://github.com/leonapivato/ai-assistant/pull/3526): the tools decision decides planning's tools, and the memory decision what planning remembers and can look up (§Words).
- Dependency: [ADR-0307](0307-a-planning-round-is-one-model-response-that-writes-its-own-message-keeps-episode-notes-and-names-what-it-was-shown-by-label.md) and [ADR-0315](0315-a-round-that-made-a-call-brings-another-round-and-the-mark-asking-for-one-retires.md), whose rounds this decision continues; [ADR-0353](0353-understanding-reads-its-stimulus-as-tagged-knowledge-then-memory-and-replies-with-what-it-understood-what-it-cites-what-is-unclear-and-where-it-belongs.md), whose tagged format §3 reuses; [ADR-0334](0334-a-prompt-is-a-template-the-hub-loads-at-start-the-owners-hub-may-override-it-from-its-data-directory-and-each-model-call-records-the-version-it-sent.md) and [ADR-0337](0337-a-prompt-change-is-judged-on-a-regression-suite-with-repeated-samples-each-recorded-call-is-asked-what-it-had-to-guess-and-a-candidate-is-promoted-after-three-clean-days.md), which govern the instruction and its suite; and [ADR-0349](0349-a-place-is-only-what-caused-an-activation-a-stop-is-reached-three-ways-running-work-is-shared-by-reading-it-and-the-newest-absorbs-what-it-continues.md), whose offers and waits §5 delivers as news. All Accepted, as their status lines leave them.
- Authorization: the owner and the prompts front rewrote planning's instruction section by section from 2026-10-28, with invented data throughout, and the design changes it needs were set out in proposal [#3526](https://github.com/leonapivato/ai-assistant/pull/3526). On 2026-10-30 the owner accepted it at `06018f611`, verbatim: "accept it, convert to the ADRs", split three ways as its acceptance comment records. The owner's words on the points this decision turns on, verbatim: on planning's text and the notes tool, "yes make it, drop the notes tool" (§7); on what the short view shows of a work's notes, "maybe it should see all of it… not that much" (§9:4); that planning reads what it writes, "not meant for any person" (§7:2); and, after the caching explanation, that the stimulus stays first in the context (§3:1). The dispatcher assigned 0356. Ratification is the dispatcher's, under the owner's delegation, once the reviews are green (§1:1).
- **Contract-surface decision, and a breaking change under golden rule 5.** It changes `core/protocols.py`: `ToolCallingCompleter.respond` takes a `PlanningExchange` in place of a `Message` sequence, and its reserved notes tool goes (§5, §13). It changes `core/types.py`: `RoundResponse` loses `notes` and `asks` and gains `continuation`; `PlanningExchange`, `ExchangeStep`, `RoundReport`, `CallResult`, `RoundContinuation`, `RecordedCall`, `RecordedDelivery`, `CallOutcomeKind`, `DeliveryStatus`, `ProjectedCall`, `ProjectedJoin` and `MessageCallPart` are added, and `ProjectedRound` and `StatementCitation` each gain a field; `EpisodeProcessingRecord` gains `call_records`, one entry per call, which the memory decision extends; `EpisodeProjection` gains the calls and the inputs taken in; and `SupportPart` gains a message call (§6, §8, §9, §13). `ActivationEffect` is unchanged. `EpisodeProcessingRecord` crosses the wire, so `PROTOCOL_VERSION` advances, and the episode store ships an upgrade (§13:4, §13:5). `Message`, `Role` and `ModelProvider` are unchanged.
- **Partially supersedes**, in the clauses §16's first table names: ADR-0284, ADR-0306, ADR-0307, ADR-0314, ADR-0315, ADR-0317, ADR-0321, ADR-0328, ADR-0334, ADR-0337, ADR-0338, ADR-0345, ADR-0349, ADR-0350 and ADR-0351.
- Partially superseded: 2026-10-30 by ADR-0357 — §3:2's table, its situation row, in the addition alone: the situation also renders the activation's place list (ADR-0350 §5:10), after the origin's line, each place under its channel heading carrying its `L` label, so a `text` call's `via` can name one (ADR-0357 §2:13). Every other clause stands. This replacement takes effect on ratification of ADR-0357. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-31 by [ADR-0359](0359-the-news-reports-a-matter-changed-and-a-memory-forgotten-since-the-work-was-shown-them.md) — §5:5, in the addition alone: the news also names each matter the work was shown that has changed since, by its `S` label, with what happened (its summary rewritten, a note gained, merged, split or gone), and each memory it was shown that the memory store no longer holds, by its `M` label, as forgotten and not to be used (ADR-0359 §2, §3), under the pass's audience (ADR-0359 §5). Every other clause stands, §5:2, §5:6 and §5:7 included. This replacement takes effect on ratification of ADR-0359. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-31 by [ADR-0360](0360-the-news-also-reports-the-time-other-works-starting-and-ending-and-what-the-person-newly-chose-to-keep-in-mind.md) — §5:5, in the addition alone: each report's news also begins with the time it was made, in the briefing's zone (ADR-0360 §2); names each activation the concurrent stimuli section would now enter and the exchange has not shown, by its `E` label, as being worked on separately, and each one shown that has ended as its short view, as short-term memory would show it (ADR-0360 §3); and names each memory newly pinned or no longer pinned, as the slot resolves pins, and each profile field the person changed since the exchange showed the person block (ADR-0360 §4), under the pass's audience (ADR-0360 §6). Every other clause stands, §5:2, §5:6 and §5:7 included. Every other clause stands. This replacement takes effect on ratification of ADR-0360. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-31 by [ADR-0361](0361-approvals-are-cards-the-person-taps-and-a-yes-is-a-one-time-ticket-for-the-exact-call.md) — §7:7, in the addition alone: a `text` call may also go into the place an input taken by a take came from, and an approval's activation's into a place on its list (ADR-0361 §6:7, §7:3). §7:10, in the addition alone: ADR-0361 §7:3 widens where a message may go. §15's approvals row is the decision ADR-0361 makes, and supersedes nothing here. Every other clause stands. This replacement takes effect on ratification of ADR-0361. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-11-01 by [ADR-0364](0364-tools-describe-themselves-in-four-parts-every-result-opens-with-its-outcome-and-connections-replace-the-place-list.md) — §3:1's sections and §3:2's table, in the additions alone: a Connections section after the situation, and the situation's row rendering the time now and the person's last stimulus alone (ADR-0364 §3:1). §3:3, in planning's briefing alone: an item's `where` is its connection's `L` label, and a tag's `from` names a person by `P` label (ADR-0364 §3:9, §4:2). §7:7 and §7:10's second sentence: a `send_text` may go into any connection the work was shown that takes one (ADR-0364 §9:3). §10:1's text, for this version of the instruction (ADR-0364 §2:1). §10:2's list, in the addition alone (ADR-0364 §2:3). §10:6's second sentence: no message tool's description says the system never claims to be human (ADR-0364 §9:10). Every other clause stands. This replacement takes effect on ratification of ADR-0364. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.

## Context

### What the owner decided

Planning is the system's deliberate thought, its System 2 (the owner's framing,
2026-10-28). It works out the goal a stimulus calls for, thinks through how to reach it,
decides how the system responds, and sees that through until the goal is met.
Understanding and recall are the path that feeds it, and neither responds. Everything that
is not deliberation moves out of planning: delivery to code, permission to authorizing,
incidental memory to the observer, a rule about one tool into that tool's description, and
style into the person's preferences, held as data.

The owner and the prompts front wrote planning's new instruction for that role, against
the input it should read rather than the one the code sends today. It has five sections and
is about a quarter the length of the live text. It is kept off GitHub until the lane that
ships it (§10:1), and this decision states only what it must carry.

The design changes the instruction needs were set out in one proposal and accepted
together. This decision takes the ones about planning's exchange with its model: the
tagged context, no switches, the continuing exchange, planning's text as its notes, the
episode's short view, and ADR-0338's instruction lines. The tools decision takes the tools: messages
as calls, planning choosing while tools carry out, and rules beside their tools. The memory decision
takes memory: what planning keeps, preferences as data, and the look-ups, the episode
look-up among them.

### What is there today

Surveyed at `58987ea15`.

- **Each round is asked afresh** (ADR-0307 §2:6). `PlanningStage.plan` in
  `orchestration/planning.py` renders the instruction as one system message and the whole
  context as one user message, a JSON object, and hands
  `ToolCallingCompleter.respond` those two `Message` values. Earlier rounds, acting's
  outcomes and digested evidence are keys of that object, re-rendered every round. The
  Protocol refuses a `Role.TOOL` turn, so no tool exchange is ever replayed.
- **Nothing caches past the instruction.** `PydanticAIToolCallingCompleter` marks the tools
  and the instruction for the provider's cache (#3077). The context changes every round, so
  every round pays for all of it.
- **Thinking is dropped.** The completer asks for the provider's thinking (#2861) and drops
  it from the response; the next round never carries it (ADR-0314 §5:3). The diagnostic
  record keeps it.
- **A round's text is its message.** It goes into the input's place as soon as the round is
  recorded (ADR-0307 §3:1). Notes and the calls a message asks about ride one reserved tool,
  `planning_round`, which `models/tool_calling.py` reads back into `RoundResponse.notes` and
  `RoundResponse.asks` (ADR-0315 §3:3, ADR-0321 §2:3).
- **The instruction switches.** `PLANNING_PROMPT` declares 14 flags and 3 values, and the
  template branches on them. ADR-0334 §2:1's table lists 6 of the flags; later decisions
  added the rest. Several capabilities are offered only where a condition holds: spawn
  (ADR-0350 §3:4), the stop call (ADR-0349 §4:6), the person model's calls, and a waiting
  round's single call (ADR-0349 §7:26).
- **The required wording** is the comment beside `PLANNING_PROMPT`, which lists the
  clauses binding the instruction under ADR-0334 §7:1.
- **Other episodes show no calls.** `_Request._episode` shows another episode's input, its
  meaning, its response, each round's message and notes, how it ended, its pending
  candidates and its evidence. It shows no call and no outcome, so a later stimulus cannot
  tell whether an email was sent unless a message happened to say so.
- **Results are not kept.** Acting's results are held in memory for the activation
  (`orchestration/held_results.py`), and each effect's outcome in the plan store
  (ADR-0306 §6). The episode records the rounds and the digests, and nothing of what came
  of each call; a held result is never saved (ADR-0308 §6:4).

### Why the model's grain matters here

A chat model expects someone to be speaking to it in the `user` turn, and answers that
someone in text. Today the `user` turn is a JSON document no one is said to have written,
and the model's text goes to the person. Planning's instruction then needs rules to stop it
writing like a chatbot to whoever sent the document, and a reserved tool to keep notes
apart from the message.

The proposal names the speaker instead. The system briefs planning, and reports back to it,
so the system is the `user` in the model's own terms. People appear only as tagged content
inside those turns, never as the speaker. Planning's text is then its reply to the system,
which is what a note is. The model answers in text whoever addresses it, and text survives
from round to round on every provider, where a model's own thinking may not.

### Words

A **work** is one activation's planning, from its first round to its last. The
**briefing** is the system's first turn of a work (§3). A **report** is the system's turn
after a round: what came of each call, then the news (§5). The **exchange** is the
instruction, the briefing, and each round with its report, in order. A **continuation** is
what a provider needs handed back with its own response to continue an exchange (§6). The
**short view** is what other work is shown of an episode (§9). A **message call** is a call
to one of the message tools the tools decision decides. **The tools decision** is the one the
dispatcher numbered 0357, deciding planning's tools, on pull request
[#3527](https://github.com/leonapivato/ai-assistant/pull/3527); **the memory decision** is the
one it numbered 0358, deciding what planning keeps and can look up, on pull request
[#3528](https://github.com/leonapivato/ai-assistant/pull/3528). Both merge after this one.

## Decision

We will have the system brief planning with tagged text, the stimulus first, and keep a
work's rounds as one continuing exchange: each round's response, its calls and their
results appended, and what changed since arriving as news. The tool set and the
instruction stay the same across every round, so the exchange caches. Planning's text is
its reply to the system, kept as its notes and written to no one. The episode records an
entry for each call, and other work sees an episode through a short view of its own parts.

### 1. Status, scope and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the dispatcher,
> under the owner's delegation, ratifies it. An assigned number or a green review alone
> does not change its status.

> **Normative.** No lane implements this decision before it merges `Accepted` (golden rule
> 5, ADR-0015 §5).

> **Normative.** The implementation is the lanes §14 sets out, cut under ADR-0137, and each
> keeps the gate green.

> **Normative.** Every earlier clause this decision replaces is replaced for an activation
> the phases plan, and for no other.

### 2. The system briefs planning

> **Normative.** Every `user` turn of planning's exchange is the system speaking: the
> briefing (§3), or a report (§5). No turn is attributed to a person.

> **Normative.** A person's words reach planning only inside a text tag that names them as
> their writer (§3:3), never as the briefer's own words.

> **Normative.** Planning's instruction says that the system briefs it with its context,
> and that results and news are the system reporting back.

### 3. The briefing: tagged text, in a fixed order

The briefing is the sections ADR-0353 §2 gives understanding, with planning's
understanding after the stimulus:

```text
# The stimulus           the framing sentence (ADR-0353 §7), then the stimulus's content
# Understanding
# Knowledge
## The situation
## Stimulus origin knowledge
## Concurrent stimuli
# Memory
## Always in mind
## Short-term memory
## Long-term memory
### Recalled memories
### Matters
## Stimulus origin memory
```

> **Normative.** The briefing is the sections above, every one of them, in that order, under
> those headings, and nothing else. It holds no JSON, and the stimulus comes first.

> **Normative.** Each section renders what the table below gives it, and nothing a section
> renders appears in another: an item shown in one section is pointed at elsewhere by its
> label, never shown again.

| Section | What it renders | Labels |
| --- | --- | --- |
| The stimulus | Every input the activation holds when its first round is asked: the trigger's, then each joined input, each with its framing sentence (ADR-0353 §7) | none |
| Understanding | The latest understanding (ADR-0353 §14:1): an `understanding` tag whose `cites` names each cited item by its label, an `unclear` container for each unclear point with a `reading` tag for each reading, and a `belongs_to` line naming the matters and running work by label, or saying it starts something new | none |
| The situation | ADR-0353 §6's three lines, the origin's line also saying whether a reply can be written there | none |
| Stimulus origin knowledge | The place window, where its kind reads it from the medium or the channel supplied it, as ADR-0353 §2's table has it | none of its own; an item linking to an activation carries that activation's `E` label as the attribute `episode` (ADR-0307 §5:6) |
| Concurrent stimuli | ADR-0349 §5's in-progress entries, as ADR-0353 §2:5–§2:7 render them; each offer open to the work (ADR-0349 §7:19), marked `offered="yes"`; and, on a waiting round, each activation the work waits on, marked `waited_on="yes"` with the decline's reason (ADR-0349 §7:26) | `E` |
| Always in mind | The person block (ADR-0338 §7:2): who the person is to the system, their fields, the memories they pinned and their pending suggestions | `M` |
| Short-term memory | The episode window's episodes that no other section renders, and the finished work this work absorbed, took over or waited on (ADR-0349 §7:10, §7:27), each as its short view (§9) | `E` |
| Recalled memories | What both recall runs kept that no other section renders: each memory, and each episode as its short view (§9) | `M`, `E` |
| Matters | Each story the activation belongs to, as ADR-0307 §6:1 gives it (its summary, its notes and episodes newer than it, when it was last tidied and how many changes have come since, the short views of the stories it is part of, marked inherited, and where the matter stands), and each story understanding cited that the activation is not in, as its short view | `S`, `N`, `E` |
| Stimulus origin memory | The place window, where its kind builds it from episodes, each of its items that is one exchange with an episode the pass holds rendered once, as that episode's short view (§9); and the episode window's episodes recorded at the stimulus's origin that origin knowledge does not render, each as its short view | `E` |

> **Normative.** The text tags, the containers, the escaping, the attributes and the naming
> of people, the system and the origin are ADR-0353 §3 and §4's, and every time is written
> as ADR-0353 §5 has it, with the additions this section names. The lane may add an
> attribute only for a fact the record holds.

> **Normative.** Planning's additions are these containers and tags, each from "the
> system" except a text tag inside them, which names its own writer: `episode`, holding one
> episode's short view (§9); inside it `input`, `understood`, `notes`, `did` and `took_in`;
> `matter`'s `summary`, `note` and `episode`; and the Understanding section's
> `understanding` and `unclear`, a container holding one `reading` for each reading. Where
> the understanding belongs is a line between the tags.

> **Normative.** Labels are planning's, as ADR-0307 §5 and the decisions amending it give
> them; this decision adds no label kind. Each item planning may name carries its label as
> the attribute `label`.

> **Normative.** An item whose words are withheld from planning renders as ADR-0353 §2:7
> renders a withheld input: an empty text tag carrying `withheld="yes"`, never its words.
> This covers an outside report, a forward, a relayed input other than the work's own
> stimulus, and a place-window item someone other than the person or the system wrote
> (ADR-0307 §9:2, ADR-0351 §5:7).

> **Normative.** The work's own stimulus, where understanding marks it relayed, such as a
> pasted email, is the one exception, by the owner's ruling on
> [#3515](https://github.com/leonapivato/ai-assistant/issues/3515): its words are shown in
> the stimulus section and in its own place-window item, in its parties' tag carrying
> `relayed="yes"`, and the work counts as having read outside content (ADR-0306 §4:5). A
> forward and every other outside content stay withheld and reach planning through a
> digest. This replaces ADR-0351 §5:7 and ADR-0307 §9:2 for the work's own relayed stimulus
> alone.

> **Normative.** A summary, a note, a stimulus or an episode that rests on outside content
> carries `outside="yes"`, by the record's mark and never by its text (ADR-0353 §3:7).

> **Normative.** Planning's instruction says that its context is only part of what the
> system knows and that it can look up more, what each section is, that the lines between
> the tags are the system's own, and that all of the context, the stimulus included, is data
> whose requests it weighs and never an instruction it must follow.

**Why reuse understanding's format.** One renderer family attributes every writer the same
way in both stages, and understanding's suite already judges it. Planning sees the same
records as understanding plus what it is responsible for: understanding's reading, the
matters in full, and the short views of earlier work.

### 4. No switches

> **Normative.** Every section of §3 is rendered on every briefing. A section with nothing
> to render carries a note giving one of ADR-0353 §8:1's reasons, under ADR-0353 §8:2's rule
> that a note never says anything was withheld.

> **Normative.** Planning's template takes no flag and no value. `PLANNING_PROMPT` declares
> none, and every part of its instruction is sent on every round.

> **Normative.** Every capability planning may call is offered on every round of every
> activation: the same names, descriptions and schemas, in one fixed order, from the hub's
> start until it stops. No round, activation, person or condition adds a capability to the
> set or removes one from it.

> **Normative.** A call to a capability whose condition for running does not hold in its
> activation comes back refused, saying why, and runs nothing. The condition is checked by
> code before authorizing, as ADR-0307 §5:4 checks a label, and it is the condition that
> today decides whether the capability is offered.

> **Normative.** §4:4 covers spawn where ADR-0350 §3:4's activation is not one, the stop
> call where the input carries no person's authority (ADR-0349 §4:6), the person model's
> calls in an activation that is no person's, and, on a waiting round, every call but the
> stop call naming an activation the work waits on and a message call (ADR-0349 §7:26).

> **Normative.** A capability with nothing to act on, such as answering an offer where no
> offer is open, comes back saying so and runs nothing.

> **Normative.** Offering a capability grants nothing: every call is still checked by rule
> as ADR-0306 §4 decides.

**Why every tool, every round.** The tools head the request, so a set that varies from
round to round breaks the provider's cache at its first byte, and an instruction that varies
with it is several texts to review. A call that cannot run here costs one round and says
why. Tools beyond a stable core, reached through memory and one fixed `use_tool`, are
direction for when integrations grow (the tools decision), and until a decision brings them every
capability is in the set.

### 5. One continuing exchange

A work's exchange is one request that grows by appending:

```text
tools          the stable set (§4:3)
instruction    planning's system text, the same on every round
briefing       the system's first turn (§3), rendered once
round 1        planning's response: its text, its calls, its continuation
report 1       the result of each call of round 1, then the news
round 2        ...
```

> **Normative.** Each round of a work is asked with the work's whole exchange: the
> instruction, the briefing, then each earlier round's response and its report, in order.
> This replaces ADR-0307 §2:6.

> **Normative.** The exchange is append-only. The briefing is rendered once, before the
> first round, and handed in byte for byte on every later round; no earlier response or
> report is edited, reordered or dropped.

> **Normative.** A report follows every round that a later round follows. It holds one
> result for each call of that round, in the round's order and under the call's id, and then
> the news. A tidy-up that started has a result saying only that it started, since no round
> waits for it (ADR-0307 §7:2); one refused before it ran has its refusal and reason, as any
> refused call does (ADR-0307 §5:3).

> **Normative.** A call's result is code's rendering of what came of it. A result resting on
> outside content is its digest's evidence, marked outside, and never the raw content
> (ADR-0307 §9:2). A result planning may name carries its `R` label (ADR-0307 §5:1). What
> each tool's result says is the tools decision's.

> **Normative.** The news is what the work's inputs hold at the report that the exchange has
> not yet shown: each offer newly open (ADR-0349 §7:19), each offer that closed, the
> finished findings or work newly read of an activation the work absorbed, took over or
> waited on (ADR-0349 §7:10, §7:27), and a stimulus taken in, with its meaning. Where nothing
> is new, the news says so.

> **Normative.** Nothing the exchange already shows is repeated in the news, and nothing is
> re-rendered to bring it up to date. A later round learns what changed from the news alone.

> **Normative.** Planning's instruction says that its rounds are one continuing exchange,
> each seeing the earlier ones, what came of them, and anything that changed since.

**Why append.** Planning keeps sight of its own rounds as it wrote them, and the context is
no longer re-read in full each round. The request is ordered for the provider's cache: the
tools and the instruction, which every work shares; the briefing, which every round of the
work shares; then what changes. The owner kept the stimulus first after the caching cost was
explained (§3:1): it sits at the head of the briefing, after the shared prefix.

### 6. Thinking, handed back

> **Normative.** `RoundResponse` carries `continuation`: what the provider needs handed back
> with this response to continue the exchange, its thinking and the thinking's signatures
> included, or `None` where it needs nothing. It is opaque outside `models/`: no other
> package reads, renders or alters it.

> **Normative.** Each earlier round's response is handed back in the exchange as the
> completer returned it, its continuation included and unchanged.

> **Normative.** An implementation accepts an exchange in which an earlier response carries
> no continuation, or one written by another model, and sends a request the provider
> accepts. How it does is the implementation's, and nothing outside `models/` relies on a
> model keeping its earlier thinking.

> **Normative.** A continuation is held only in memory, for the work's life, and in the
> diagnostic record (ADR-0314 §5). It is never recorded in the episode, never crosses the
> wire, and never reaches any text planning or anyone else reads. This replaces ADR-0314
> §5:3's *the next round never carries it*, for planning's own exchange alone.

**Why opaque.** Providers differ in what they need back: Anthropic's thinking blocks carry
signatures that must come back unchanged on the same model, and other providers need
nothing. pydantic-ai models each provider's parts; `core` should name none of them. The
diagnostic record already keeps the provider's whole response (ADR-0314 §5:2), so nothing
new is written there.

### 7. Planning's text is its notes

> **Normative.** A round is one model response in the provider's native tool-calling shape,
> with two parts: its text, which is all the text it wrote outside a call, and its calls.
> This replaces ADR-0315 §3:1.

> **Normative.** A round's text is its reply to the system and is kept as the round's
> episode notes (ADR-0307 §4). It is written into no place, sent to no one, and goes through
> no authorizing. It is not meant for any person, and those who inspect the system, such as
> the owner in the activation viewer, can still read it.

> **Normative.** A round writes no message. What people receive comes only from message
> calls, whose rules are the tools decision's.

> **Normative.** No tool carries the notes and no tool name is reserved. `RoundResponse`
> loses `notes` and `asks`, and the reserved tool `planning_round` goes. This replaces
> ADR-0315 §3:2 and §3:3.

> **Normative.** No part of a response names the calls a message asks about: `RoundResponse`
> carries no `asks`, and no implementation carries a naming in the provider's native shape.
> This replaces ADR-0321 §2:3 in the response's carrying of the naming alone; where the calls
> are named is the tools decision's.

> **Normative.** Planning's instruction says that text it writes outside a call is its reply
> to the system, kept as its notes, which its later rounds and later work see and which is
> not meant for any person, and that what people receive comes only from its calls.

> **Normative.** A `text` call is the round's message in the form of a call. It is checked
> by its place alone, as ADR-0306 §4:7 checks the round's own message, on the place it names
> or the tool resolves: that place is the input's, or one on the place list where ADR-0350
> §6:7 gives one, and the outside-content rule never applies to it. This replaces ADR-0306
> §4:7's *the round's own message*, in its subject alone.

> **Normative.** A `text` call is claimed and recorded as ADR-0306 §5 decides for a message:
> its effect record carries the place and, once done, the position the medium recorded, so
> the place window links it to its activation, and names the round that proposed it
> (ADR-0307 §10). This replaces ADR-0306 §5:3–§5:5's *message*, in its subject alone: a
> message is a `text` call, and a round's text is none.

> **Normative.** An `email` call is a call like any other: declared under ADR-0306 §2,
> checked by rule under ADR-0306 §4:1, and claimed and recorded as a call in the world under
> ADR-0306 §5, as `send_email` is today. A `speak` call is its own decision's.

> **Normative.** Nothing in this section widens where a message may go or who it may reach:
> the places a `text` call may name are the places the round's own message could go into
> before this decision.

**The risk this accepts.** A reply meant for a person, written as text, would be kept as a
note and never sent. The briefing framing makes it unlikely, because the model knows who
reads its text, and the first suite case checks it (§11:1). If it fails often, the fallback
is a notes tool, with stray text sent back as news (Alternatives).

### 8. What the episode records

> **Normative.** Each round is recorded as `PlanningRound` is today, its response's text
> recorded as the round's `notes` (empty text as none) and marked as ADR-0307 §4:3 marks
> notes. A round recorded under this decision carries no `text`, and so no `place`
> (ADR-0350 §12:8). A round recorded before this decision keeps its `text` as the message it
> wrote and its `place` as where that went, for every reader.

> **Normative.** `EpisodeProcessingRecord` gains `call_records`, one entry for each call a
> round proposed, refused calls and look-ups included, naming its round and its call by id.
> It is the one entry per call the memory decision extends, and no other field records what
> came of a call.

> **Normative.** An entry holds: the call's capability; whether that capability declared an
> effect when the call ran (ADR-0312); and its outcome as planning was shown it, one of
> *done*, *not done*, *refused*, *needs the person* and *unknown*, with its reason where it
> has one, or no outcome where §8:6 records the entry before one is known.

> **Normative.** The entry of a message call that was sent, or whose sending was attempted,
> also holds what it sent: the words, after any rewording and with any exact lines; where it
> went, the platform and the place; and how it went, *sent*, *delivered*, *read*, *failed*
> or *unknown*, as the tools decision's result reports it. A message call refused or come
> back before anything was sent, such as one naming a place it was never shown, holds none.

> **Normative.** An entry holds no result's body. What each call showed, kept by reference
> for the episode look-up, is the memory decision's addition to the entry, and a result that
> carried outside text is on the record only through its digests (ADR-0308 §6:4).

> **Normative.** An entry is appended once its call's outcome is known, before the next
> round's request and whether or not another round runs, and every earlier entry is
> unchanged. A tidy-up that starts has its entry appended when it starts, with no outcome, and
> its outcome stays in the story's version log (ADR-0307 §7:1); one refused before it ran is
> recorded refused, as any call is. A call whose outcome is not known when the
> episode freezes has its entry appended with the freezing revision, with no outcome, and its
> outcome stays on its effect record (ADR-0306 §6). An append is recorded as a round's is
> (ADR-0307 §2:4): a failure is a capture failure that holds nothing back.

> **Normative.** An entry rests on outside content where its call's result was a digest's
> evidence or the work had read outside content when the call was proposed, and it is marked
> so, as the round's notes are (ADR-0307 §4:3).

> **Normative.** An entry is placed for the owner alone, as episode notes are (ADR-0307
> §4:4), and an activation's own planning is shown what came of its calls on every pass, in
> its exchange (ADR-0312 §4:1).

> **Normative.** `EpisodicMemory.outcome` is still set once, as the activation's messages in
> the order they went out (ADR-0307 §10): the words each message call delivered, as its
> entry holds them.

### 9. The short view

Short-term memory, recall and a matter show another episode through its short view: a
selection of the episode's own recorded parts, made by code, never a summary. In the order
they happened:

1. the input, and the meaning understanding recorded;
2. then planning's notes, each call with an effect with what came of it, and each offer
   taken in;
3. then how it ended.

> **Normative.** The short view is rendered from the episode's projection alone (ADR-0284
> §8:3), which carries what it needs (§13). It is an `episode` container under its `E` label
> holding, in this order: its `input`, as ADR-0353 §3 tags a stimulus's words, or an empty
> `input` saying the section it is shown in where §3:2 shows it elsewhere; its `understood`
> meaning; then, in the order recorded, each round's `notes`, a `did` for each call whose
> entry records an effect, and a `took_in` for each input it took in (ADR-0349 §7:7);
> and its ending as the container's `ended` attribute (ADR-0284 §8:6).

> **Normative.** A `did` names the call's capability and its arguments, as its round
> recorded them, and gives its entry's outcome with its reason. A message call's `did` gives
> the words it delivered, where they went and how. Look-ups and every other call whose entry
> records no effect are left out.

> **Normative.** An episode recorded before this decision shows each round's message, read
> from the round's `text`, as a `did` of the message it wrote, and its notes as `notes`.

> **Normative.** The short view shows every round's notes, oldest first, up to a bound a
> composition-root constant holds. Past it, the oldest are left out and the view says how
> many were, and that the episode look-up (the memory decision) reads them.

> **Normative.** The short view applies the reader's audience part by part, as the episode
> window does (ADR-0307 §6:4, ADR-0312 §4:2): a part placed for someone else is left out with
> no marker. On a pass where records placed for the owner alone may not be shown, it shows
> the input, the meaning and how the episode ended, and nothing of its notes or its calls.

> **Normative.** A part resting on outside content is shown only through its digest's
> evidence or as withheld, never raw (ADR-0307 §9:2), and the work that is shown it has read
> outside content.

> **Normative.** No short view, look-up or rendering shows a round's thinking or its
> continuation.

> **Normative.** The episode look-up, which reads an episode's full record by its `E` label,
> is the memory decision's.

**Why calls, and not the whole episode.** Today's view shows no calls, so a later stimulus
cannot tell whether an email went. A whole episode is large, brings back memories forgotten
since through old search results, and shows stale results as if current. The short view
keeps what changed the world; the look-up has the rest.

### 10. The instruction, and its required wording

> **Normative.** The default `src/ai_assistant/orchestration/planning.txt` becomes the
> instruction the owner and the prompts front wrote, in the shared document "Planning
> prompt: working draft", tab "Draft prompt (editable)", as it stands at the commit of lane
> P3 that ships it, with no change but what a ratified clause requires. Its five sections
> are its responsibility, the context it is given, how that context is laid out, thinking a
> response through, and acting in rounds.

> **Normative.** The list beside `PLANNING_PROMPT` of what the instruction must say
> (ADR-0334 §7:1) is rewritten to the clauses that bind it after this decision, the tools decision
> and the memory decision, and no others. Of this decision's, they are §2:3, §3:9, §5:7 and §7:6; of
> earlier decisions', ADR-0315 §4:3, read with §10:4, and ADR-0307 §2:5 and §9:3.

> **Normative.** Each requirement the old list names is accounted for by the table below,
> and a row naming the tools decision leaves the instruction's list where the tools
> decision, merged, places the requirement in a tool's description.

| The old list's requirement | After this decision |
| --- | --- |
| Where the place takes no message (ADR-0307 §3:8); that the text is the system's own words to the person (ADR-0307 §3:3); that empty text writes no message (ADR-0307 §3:2) | Retired: the text is notes (§7). The situation says whether a reply can be written at the origin (§3:2) |
| That acting on a request is always said | Retired: no clause requires it. Confirming what was done is a preference (the memory decision) |
| How rounds follow calls (ADR-0315 §2, §4) | Stays, as ADR-0315 §4:3 and §10:4 have it |
| How approval works and explaining what is asked about (ADR-0321 §2:4, §2:9) | The tools decision: in the description of `text`'s `asks` |
| The line of care (ADR-0321 §2:11) | Stays: the instruction's line on finding the goal out first where getting it wrong would matter carries it |
| How a round asks, an approved action, a deny said plainly, and that an activation that cannot message asks nothing (ADR-0321 §2:1–§2:3, §2:5–§2:8, §2:10, §2:12, §3:5, §3:8–§3:9, §4:2, §4:11, §7:3, §8:7) | Not instruction wording: what a call needing the person, a deny or an approved action means comes back in the call's result, and approvals stay stopped (ADR-0353 §11) until the authority decision that restarts them |
| The story calls (ADR-0300 §10, ADR-0303 §9, ADR-0307 §5:3–§5:5, §7) | The tools decision: in the descriptions of the matter calls |
| What a candidate is for, when to name a memory, when to note reliance (ADR-0329 §5:1, §6:1–§6:5, §6:8) | The tools decision: in the descriptions of `remember` and the reliance call; what memory does with them is the memory decision's |
| Spawn's four points (ADR-0350 §9:3) | The tools decision: in the reminders' descriptions |
| A scheduled message names its place by label (ADR-0350 §6:7) | Retired: the text is no message, and a message call names where it goes (the tools decision, §16) |
| Taking an offer unless something done would change (ADR-0349 §7:19) | The tools decision: in the answer call's description |
| A field outweighs a memory (ADR-0338 §3:10); use the block, never recite it, address by name (§7:8); no preference changes what is true, and never claim to be human (§5:6); raise a suggestion only by asking (§7:8) | §10:5–§10:7 |

> **Normative.** That a tidy-up brings no round is said by the tidy-up's description, as
> the tools decision words it, and planning's instruction need not say it. This replaces ADR-0315
> §4:3 in its tidy-up exception alone.

> **Normative.** The person block, which is data (ADR-0338 §7:6), says that its fields are
> the person's current choice and outweigh any memory stating another value for them, and
> planning's instruction need not say it. This replaces ADR-0338 §3:10's *planning's
> instruction says that a field outweighs any memory stating another value for it*.

> **Normative.** That no preference, pin or field changes what is true, what the system
> judges best or any rule is carried by §3:9's line that everything in the context is data
> to weigh. That the system never claims to be human is said by each message tool's
> description (the tools decision). This replaces ADR-0338 §5:6's second sentence; its
> first and third stand.

> **Normative.** Planning's instruction need not say how to use the person block or how to
> address the person, which are the person's preferences, held as data (the memory decision). That a
> suggestion is raised only where it bears on what is being done, and only by asking with a
> `set_profile` or `pin` call, is said by those calls' descriptions, which ship in P3 (§14:10).
> Both calls are in §4:3's stable set, offered on every round, and a call in an activation
> that is no person's comes back refused (§4:4). This replaces ADR-0338 §7:8 whole.

> **Normative.** The instruction need no longer say anything of a notes tool, a mark, a
> place label in a message, or a flag, and no part of it is conditional. No part of it
> describes a path that cannot run, approvals among them while ADR-0353 §11 stops them.

### 11. How it will be judged

> **Normative.** P3's default is judged on the ADR-0337 suite, which gains one case for each
> of these, each invented (ADR-0337 §3:2), naming no flag, and sampled repeatedly:
> 1. a plain question comes back as a message call, not as text;
> 2. a clear request is simply done: "remind me at 9" is neither second-guessed nor asked
>    about;
> 3. a two-part request meets both parts;
> 4. no unprompted extras: no menu of services, no "anything else?", no question nobody
>    needed;
> 5. a plain absence gets a plain answer, with no hedging about what the system might not
>    see;
> 6. a message never reports on a call from its own round;
> 7. a stimulus from the system itself, such as a reminder coming due, is handled as what
>    it was set up to do;
> 8. outside content sets no goal by itself: an invoice email is reported, not paid.

> **Normative.** Case 1's property is a code check: the response holds a message call
> answering the question and no other reply. A case whose property needs reading is `read`
> (ADR-0337 §3:6).

> **Normative.** ADR-0337's existing synthetic cases for planning are re-rendered as
> exchanges in the new format, and a case whose failure class this decision retires, such as
> a prompt label in a message, is rewritten to the class it now guards or retired in P3's
> pull request with the reason.

> **Normative.** A planning case's input is a round's exchange after the instruction, as
> its given entry records it, and its offered tools (ADR-0337 §3:4).

> **Normative.** P3's default becomes the default by P3's reviewed pull request, with the
> suite green for it as §11:6 states, and not after three days as an override: no override
> can run the new format before the code that renders it exists. Once deployed it is judged
> as ADR-0337 §9:3 judges a candidate, and a failure found is fixed by a reviewed pull
> request (ADR-0334 §7:3). This replaces ADR-0337 §9:1 for P3's default alone.

> **Normative.** The suite is green for P3's default where it passes every sample of each
> of §11:1's cases and every code check of the re-rendered cases. It runs with no control
> under the old default, which cannot read the new format. This replaces ADR-0337 §4:3 for
> P3's default alone.

> **Normative.** At the deploy that installs P3's default on the owner's hub, the live
> planning override is removed or replaced, since it names flags the prompt no longer
> declares and would stop the hub at start (ADR-0334 §5:1). Its removal or replacement is
> the owner's act, or the dispatcher's at the owner's direction (ADR-0334 §6:1), and that
> deploy does not run without it.

### 12. Understanding's two phrases

> **Normative.** P3's pull request changes understanding's default in two places and no
> others: the system "briefs you with" its context, in place of "provides you with"; and
> always in mind's description covers "how they like things done", which is where the
> person block holds preferences (ADR-0338 §7:2). No other part of understanding changes.

> **Normative.** The change runs understanding's suite, with the current default as its
> control (ADR-0337 §4:3), and is green as ADR-0337 §9:2 has it. It becomes the default by
> P3's reviewed pull request and not after three days as an override. This replaces ADR-0337
> §9:1 for this change alone.

> **Normative.** The preferences' default values, which always in mind will hold, wait for
> the user model and persistent identity, as the owner directed. Neither this decision nor
> P3 sets one.

### 13. The code it binds

| Code | Change |
| --- | --- |
| `ToolCallingCompleter` | `respond(self, exchange: PlanningExchange, tools: Sequence[OfferedTool], *, model: str \| None = None) -> RoundResponse`. It takes no `Message`, refuses two tools sharing a name and reserves no tool name. Its docstring states §5, §6 and §7 in place of *each round is asked afresh* |
| `PlanningExchange` | New frozen record: `instruction`, non-blank; `briefing`, non-blank; and `steps: tuple[ExchangeStep, ...]`, oldest first. Its call ids are distinct across every step |
| `ExchangeStep` | New frozen record: `response: RoundResponse`, an earlier round's response as returned; and `report: RoundReport`, the turn after it |
| `RoundReport` | New frozen record: `results: tuple[CallResult, ...]`, one for each call of its step's response, in that response's order and under its ids; and `news`, non-blank |
| `CallResult` | New frozen record: `call_id` and `text`, non-blank |
| `RoundContinuation` | New frozen record: `model`, the `"provider:model"` that wrote the response, and `parts`, an opaque JSON value only `models/` reads |
| `RoundResponse` | `text`, `calls` and `continuation: RoundContinuation \| None`. Loses `notes` and `asks` |
| `PlanningRound` | No field changes. A round recorded under this decision takes its response's text as `notes` and carries no `text` or `place`; how `asked` is filled is the tools decision's |
| `RecordedCall` | New frozen record: `round` and `call_id`; `capability`; `effect: bool`; `outcome: CallOutcomeKind \| None` and `reason`, non-blank or `None`, a reason only with an outcome; `delivered: RecordedDelivery \| None`, only on a message call that was sent or attempted (§8:4); `recorded_at`; and `marked: bool`. The memory decision adds what the call showed |
| `CallOutcomeKind` | Moves from `orchestration/planning.py` into `core`, its members unchanged: `done`, `not_done`, `unknown`, `needs_you`, `refused` |
| `RecordedDelivery`, `DeliveryStatus` | New frozen record: `words`, non-blank; `went`, the platform and the place; `status: DeliveryStatus`; and `reason`, non-blank or `None`. New closed enumeration: `sent`, `delivered`, `read`, `failed`, `unknown` |
| `EpisodeProcessingRecord` | Gains `call_records: tuple[RecordedCall, ...]`, empty by default; `schema_version` advances by one. Its validator refuses an entry naming a round it does not hold, or a call that round did not propose, and two entries for one call |
| `core: episode_extends` | Also admits entries appended at the end of `call_records`, every earlier entry unchanged (ADR-0286 §3:2–§3:3) |
| `ProjectedRound` | Gains `position`, the round's index among every round the episode recorded, so a round the projection omits for having nothing to show still keeps the others in order |
| `ProjectedCall` | New frozen record: one entry as a reader is shown it: its round's position, in `ProjectedRound.position`'s numbering, the capability, the arguments its round recorded, cut to the projection's excerpt bound, `effect`, the outcome and reason, the delivery and `marked` |
| `ProjectedJoin` | New frozen record: one input the episode took in (ADR-0349 §7:7), attributed and withheld as the projection's input is, with the position, in the same numbering, of the round before which it was taken |
| `EpisodeProjection` | Gains `calls: tuple[ProjectedCall, ...]` and `joined: tuple[ProjectedJoin, ...]`, empty by default |
| `core/episode_encoding.py: project_episode` | Fills `calls` and `joined` where `owner_records` admits episode notes, and leaves them empty otherwise (§9:5); a round recorded before this decision projects its `text` as its message, as now |
| `MessageCallPart` | New member of `SupportPart`: `episode`, `round` and `call_id`, the message one message call sent, resolved to its entry's words. `RoundMessagePart` stays, for rounds recorded before this decision |
| `StatementCitation`, `statement_citations` | `StatementCitation` gains `call_id: Identifier \| None`; `statement_citations` cites a support at either message part (§13:3) |
| `ActivationEffect` | Unchanged: a `text` call's record is a message's, and an `email` call's a call's (§7:7–§7:9) |
| `PLANNING_PROMPT` | Declares no flag and no value (§4:2); its required-wording list is §10:2's |
| `PydanticAIToolCallingCompleter` | Translates the exchange into the provider's messages: the instruction as the system part, the briefing as a user part, each response handed back as the provider returned it from its continuation, each report as the provider's tool-result parts followed by the news; marks the newest report for the cache; and returns the response's continuation. `ROUND_TOOL` goes |
| `models/follow_up.py: follow_up_round`, the replay seam | Send a round's whole exchange, as `respond` sends it; a candidate's replay hands earlier responses back without their continuations where its instruction differs from the recorded one (§6:3) |
| `ModelProvider`, `Message`, `Role` | Unchanged |

> **Normative.** `core/types.py`, `core/protocols.py` and `core/episode_encoding.py` make the
> changes the table names, with each record's validator, and nothing else of `core` changes.

> **Normative.** A support pointing at a `MessageCallPart` takes the origin ADR-0328 §4:2's
> origin table gives a round's message, by the same fact (ADR-0328 §4:3), and resolves to
> nothing where the entry holds no delivery. A support pointing at a `RoundMessagePart`
> resolves as before.

> **Normative.** Every rule and reader that reads a support pointing at a round's message
> reads one pointing at a `MessageCallPart` as the same kind of part: the writer's check for
> a memory marked `assistant_statement` (ADR-0345 §8:3), the citation every projection
> conveys (ADR-0345 §12:4), `statement_citations`, and the resolution of a part's text.
> `StatementCitation` gains `call_id`, set where the message is a call's, so two messages
> of one round are cited apart.

> **Normative.** `PROTOCOL_VERSION` advances in the lane that adds `call_records` to
> `EpisodeProcessingRecord`, in that change (ADR-0124 §9), with the wire surface and type
> closure and the memory and engine conformance suites extended to the shape.

> **Normative.** That change is a schema change of the episode store (ADR-0326 §2:3). Its
> lane advances the store's label, ships ADR-0326 §4:1–§4:2's upgrade and its test over a
> file the previous release wrote, carries every stored record whole with `call_records` empty,
> and raises the store's shape in `scripts/upgrade_stores.py` (ADR-0326 §7:1).

> **Normative.** Planning's given entry records the work's exchange as handed in, so a
> round can be replayed and followed up from its entries alone (ADR-0335 §4:8, ADR-0337
> §6:3). A followed response's thinking reaches the follow-up request, a real `follow_up`
> case that keeps it, and the later rounds of its own work, and nothing else. This replaces
> ADR-0337 §6:6's *and nothing else*, in the addition alone.

### 14. Delivery

The lanes, each after this decision merges `Accepted`, are delivered under
[milestone 18](https://github.com/leonapivato/ai-assistant/milestone/18), "Planning as
System 2", whose acceptance is
[#3530](https://github.com/leonapivato/ai-assistant/issues/3530):

1. **P1, the contract unit with its primary implementation** (ADR-0137 §2:1): §13's
   `ToolCallingCompleter`, exchange, `RoundContinuation` and `RoundResponse` rows, the
   conformance suite, the canonical fake in `ai_assistant.testing`,
   `PydanticAIToolCallingCompleter` and the follow-up and replay seams in `models/`, and in
   `orchestration/planning.py` the least that keeps the gate green: one briefing of today's
   rendered context, each round's text recorded as its notes, and nothing read from `asks`.
2. **P2, the exchange**, briefed against merged P1: the work's exchange held across rounds
   and appended (§5), the reports and the news, the `text` and `email` calls' checks and
   records (§7:7–§7:9), each call's entry recorded with the episode (§8), the projection's
   `calls` and `joined` (§13), `MessageCallPart` with its resolution,
   the stable tool set and the refusals of §4:4–§4:6, and the episode store's upgrade with
   `PROTOCOL_VERSION`'s advance (§13:4, §13:5).
3. **P3, the briefing and the instruction**, briefed against merged P2, whose projection the
   short view reads, and against
   the tools decision's merged message tools: §3's briefing, the short view (§9), the default prompt
   (§10:1) with no flag, the required-wording list (§10:2), the suite's cases (§11),
   understanding's two phrases (§12), and, in the same change, the tools decision's moved
   rules and the `set_profile` and `pin` descriptions (§10:7).
4. **P4, the readers** (ADR-0137 §4:1), briefed against merged P2: `project_episode`, the
   observer, the matters pass, the story tidy-up, episode inspection and the activation
   viewer, each reading a round's notes and each call's entry, and a round's text as a
   message only on a round recorded before this decision; and the observer's citing of a
   message by `MessageCallPart`.

> **Normative.** P1 may touch `core`, `testing`, `models`, their tests,
> `orchestration/planning.py` and its tests, and any test that scripts a round's response.
> In other modules it may remove what reads `notes` or `asks` from a response, so the gate
> stays green, and adds nothing a reader shows.

> **Normative.** P2 may touch `core` for §13's `EpisodeProcessingRecord`, `RecordedCall`,
> `RecordedDelivery`, `DeliveryStatus`, `CallOutcomeKind`, `episode_extends`, projection and
> `MessageCallPart` and `StatementCitation` rows, `orchestration/support_parts.py`,
> `memory` and `testing` where they read a support's part or for the store's upgrade,
> `wire` for the wire shape,
> `orchestration/planning.py`, `orchestration/phase_path.py`, `orchestration/held_results.py`,
> `scripts/upgrade_stores.py`, and their tests.

> **Normative.** P3 may touch `orchestration/planning.py` and `planning.txt`,
> `orchestration/understanding.txt` for §12 alone, what the planning phase hands the stage
> in `orchestration/phase_path.py`, `prompt_cases/`, `scripts/prompt_replay.py` with its
> tests, and the description of each capability §14:10 and §10:7 move a rule into, wherever
> it is declared, for its description alone. It is one pull request with the tools
> decision's lane that moves the rules, under both lanes' fences.

> **Normative.** P4 may touch `orchestration/observer/`,
> `orchestration/matters_pass.py`, `orchestration/story_tidy_up.py`,
> `interfaces/episode_inspection.py`, `scripts/activation_viewer.py`, and their tests.

> **Normative.** P1's tests include, each failing on an implementation that meets only the
> others: an exchange of a briefing alone is sent with the instruction as the system part
> and the briefing as one user part; an exchange with steps sends each earlier response
> back as returned, then each report's results as the provider's tool-result parts under
> their call ids and in order, then its news; a response's text is the concatenation of its
> text parts, and a thinking part is no part of it; a response's continuation, handed back
> unchanged, is in the next request as the provider returned it; an exchange whose earlier
> response carries no continuation, or one naming another model, is sent and accepted; a
> report whose results name a call its response did not make, miss one or reorder them is
> refused by the type; two steps reusing a call id are refused by the type; two tools
> sharing a name are refused before any model is contacted; a tool named `planning_round`
> is offered like any other; and the newest report carries the cache mark.

> **Normative.** P2's tests include: the briefing a work's later round sends is
> byte-identical to its first round's; a report follows each round a later round follows,
> with one result per call; a result resting on outside content is its digest's evidence,
> marked; news lists an offer newly open, says nothing has changed where nothing has, and
> never repeats what an earlier turn showed; a `text` call naming a place off its
> activation's places is refused by the message place check, and one done carries its
> position on its effect record; the tools offered are identical, names,
> descriptions, schemas and order, on every round of two activations of different persons
> and kinds; a spawn call from an activation ADR-0350 §3:4 does not admit, a stop call
> without the person's authority, and a non-stop call on a waiting round each come back
> refused with the reason and run nothing; an entry is recorded for every call, a refused
> call and a look-up included, once its outcome is known, the last round's included, and a
> message call's entry holds its delivered words, where they went and how; two entries for
> one call are refused by the type; a `text` call naming a place it was never shown records
> an entry, refused, with no delivery; a tidy-up's entry is recorded at its start with no
> outcome and the next round does not wait for it, while a tidy-up naming a story it was
> never shown, beside a look-up, is reported and recorded refused with its reason; a call
> still running when the episode
> freezes is recorded with no outcome; the projection carries an episode's calls and joined
> inputs where owner-only records are admitted and none otherwise, and a short view of an
> episode whose call-only round precedes a round with notes shows the call first; a support at a
> `MessageCallPart` resolves to the words sent, and to nothing for a call that sent none; a
> memory marked `assistant_statement` resting on a `MessageCallPart` is written, and cited
> with its call, apart from another message of the same round; and
> an episode stored before the upgrade reopens with `call_records` empty and every other
> record whole.

> **Normative.** P3's tests include: every section renders in every state the pass can
> reach, each empty one with a note naming one of ADR-0353 §8:1's reasons; an item shown in
> origin knowledge is pointed at, not repeated, by an episode in short-term memory; a short
> view lists notes, each effectful call with its result and each offer taken in, in the order
> recorded, and no look-up; an episode recorded before this decision shows its messages as
> `did`s; a work's notes past the bound are cut oldest first with the count said; on a pass
> that may not be shown owner-only records, a short view shows no notes and no call; a
> withheld item renders as an empty tag; the prompt declares no flag and no value; and the
> default renders with none set.

> **Normative.** P4's tests include, for an episode recorded after this decision and one
> recorded before: the observer, the matters pass and the tidy-up read a round's notes from
> `notes`, and a message from its entry after and from its round's `text` before; the
> observer cites the first by `MessageCallPart` and the second by `RoundMessagePart`; and
> episode inspection and the viewer show each call's entry, and an older round's message.

> **Normative.** P2 builds the entry §8 decides, and the memory decision's lanes extend it:
> one entry per call, whichever lane builds second extending what the first built.

> **Normative.** P3's pull request carries the tools decision's moved rules, each into its
> description, so that every rule leaves the instruction in the change that puts it in its
> description, and no build carries neither.

> **Normative.** No release carrying P1 is deployed to a person's hub before P2, P3, P4 and
> the tools decision's message tools have merged. They reach a hub together, in one deploy, and no
> deploy between them is owed.

### 15. What this decision does not decide

| Not decided here | Where it goes |
| --- | --- |
| The message tools, "act, or come back", the asking message and the moved rules | The tools decision |
| What planning keeps, preferences as data and their space, the missing look-ups, and the episode look-up | The memory decision |
| Approvals: how a yes is recognised again, and where approved actions (ADR-0321 §4:2) render within §4:3's stable set. They stay stopped (ADR-0353 §11) | The authority decision that redesigns approvals |
| Where the place list (ADR-0350 §5:10) renders | The tools decision, which decides where a message goes |
| Whether a result needs an `R` label for a follow-up beyond ADR-0307 §5:1's | A later decision, on evidence |
| How "what was done" renders for each tool in brief | P3, under §9:2 |
| The round limit, and caching details for each provider | #2589, and `models/` |
| Whose side planning takes in a household | Deferred while the owner holds full control |
| Thinking summaries in the look-up, marked | A later option, if planning needs its old reasoning |

> **Normative.** Each item the table names takes a decision of its own before any lane
> builds it, except where its row names a lane.

### 16. Relationship to earlier decisions

Superseded in part. Every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0284 | §8:1's projection, in the addition alone: the calls and the inputs taken in, under owner-only placement | §13, §9:5 |
| ADR-0306 | §4:7's *the round's own message* and §5:3–§5:5's *message*, each in its subject alone: a `text` call, checked by its place alone and claimed and recorded as a message | §7:7, §7:8 |
| ADR-0307 | §9:2, for the work's own relayed stimulus alone (#3515); §2:6, whole: one continuing exchange; §3:1, §3:2 and §3:8, whole: a round's text is its notes and is written into no place; §3:4 and §3:5, in their subject alone: what they say of a round's text as a message holds of its message calls, as the tools decision decides; §4:1's *as part of its response*: the notes are the response's text; §6:1, in how it is given: earlier rounds, acting's outcomes and digested evidence reach planning through the exchange, and the rest as §3 lays it out; §10's `ToolCallingCompleter`, `RoundResponse` and `PlanningRound` rows | §3:7, §5:1, §7:2, §7:3, §3, §13 |
| ADR-0314 | §5:3's *the next round never carries it*, for planning's own exchange alone | §6:4 |
| ADR-0315 | §3:1, §3:2 and §3:3, whole: two parts, no reserved tool; §4:2, in its subject alone: a round writes a message only by a message call; §4:3, in its tidy-up exception alone; §5's `RoundResponse`, `ToolCallingCompleter` and pydantic-ai completer rows | §7:1, §7:4, §7:3, §10:4, §13 |
| ADR-0317 | §2:2, in its subject alone: an activation that made no message call writes nothing, where it said *with every round's text empty*; §3:4's *a message a round wrote*, in its subject alone: a message call | §7:3 |
| ADR-0321 | §2:3, in the response's carrying of the naming alone: `RoundResponse` carries none, and where the calls are named is the tools decision's | §7:5 |
| ADR-0328 | §4:1's points-at field and §4:2's origin table, in the additions alone: a message call, as `MessageCallPart`, taking a round's message's origin | §13:2 |
| ADR-0345 | §8:3's and §12:4's *a round's message*, in the addition alone: a message call's message, as `MessageCallPart`, cited with its call | §13:3 |
| ADR-0334 | §2:1's table, planning's row, in its flags and values: none | §4:2 |
| ADR-0337 | §9:1 and §4:3, for P3's default alone; §9:1, for understanding's two phrases alone; §6:6's *and nothing else*, in the addition alone: the later rounds of its own work | §11:5, §11:6, §12:2, §13:6 |
| ADR-0338 | §3:10's *planning's instruction says that a field outweighs any memory stating another value for it*: the block says it; §5:6's second sentence: the data line and the message tools carry it; §7:8, whole | §10:5, §10:6, §10:7 |
| ADR-0351 | §5:7, for the work's own relayed stimulus alone: planning is shown its words, marked relayed (#3515) | §3:7 |
| ADR-0349 | §4:6 and §7:26, each in what is offered alone: the stop call and the stable set are offered on every round, and a call whose condition fails comes back refused | §4:3, §4:5 |
| ADR-0350 | §3:4, in what is offered alone: spawn is offered on every round, and a spawn ADR-0350 §3:4's activation does not admit comes back refused; §6:7's *each of its messages names, by its place label, the one place on the list it goes into* and *as ADR-0307 §3:8 keeps the text*: a round's text is no message, and a message call names where it goes, as the tools decision decides, under the same list and the same check | §4:3, §4:5, §7:3 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0306 §4:1–§4:6, §5:1, §5:2, §5:6–§5:13, §6 | Nothing: every call is still checked and claimed; offering every capability grants nothing (§4:7), and `ActivationEffect` keeps its two forms |
| ADR-0307 §2:3–§2:5, §3:6, §3:7, §4:2–§4:6, §5, §6:2–§6:6, §7, §8, §9 | Nothing: rounds are still recorded and never edited, calls still run in parallel, labels hold for the work, the tidy-up runs on its own and records its outcome in the version log (§8:6), when rounds run stands, and planning never reads raw outside content |
| ADR-0307 §3:3 | The tools decision's: who writes a message's words, now that a message is a call |
| ADR-0312 §4 | Nothing: an activation's own rounds, notes and evidence reach its own planning on every pass, now through the exchange (§5:1) |
| ADR-0315 §2, §3:4, §4:1 | Nothing: a round with a call other than a tidy-up brings another, and no part of a response asks for one |
| ADR-0321 §2:4–§2:12, §4 | The tools decision's where it moves them: the asking message and the exact line; the rest stand, and approvals stay stopped (ADR-0353 §11) |
| ADR-0329 §7:1 | Nothing: the observer reads an episode once it leaves the episode window, and reads its notes and entries as the episode keeps them |
| ADR-0334 §4, §5, §7 | Nothing: a template with no flag renders under the one combination; an override naming a flag stops the hub (§11:7) |
| ADR-0335 §4:6, §4:8, §4:10 | Nothing in their words: a planning call's recorded request is its exchange (§13:6), and a replay still sends once and continues nothing |
| ADR-0337 §3:4, §9:2 | Nothing in their words: a planning case's input is its exchange as the given entry records it (§11:4) |
| ADR-0338 §7:2, §7:6, §7:7 | Nothing: the block is data, rendered always in mind, its memories labelled `M` |
| ADR-0349 §7:10, §7:19, §7:27 | Nothing in their words: what they show at every round reaches planning at its first round in the briefing and after it as news (§5:5) |
| ADR-0350 §6:8, §12:8 | Nothing: the list and its interim stand, and a round recorded under this decision carries no `place` (§8:1) |
| ADR-0353 | Nothing: its required-wording list (§13:2) pins neither phrase §12 changes, and its format is reused (§3) |
| ADR-0355 | Nothing: structured calls are not planning's, and their thinking stays in the diagnostic record |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0284, ADR-0306, ADR-0307, ADR-0314, ADR-0315, ADR-0317, ADR-0321,
> ADR-0328, ADR-0334, ADR-0337, ADR-0338, ADR-0345, ADR-0349, ADR-0350 and ADR-0351, atomically with this ADR under ADR-0070 and ADR-0082,
> preserving their ratified bodies. The replacements take effect on this ADR's ratification.

### 17. The format, worked

Invented data throughout. The briefing of a work's first round, trimmed to the sections that
hold something:

```text
# The stimulus
A stimulus reached the system at 5:40 pm on Thursday 30 October 2026: a message Leo typed on Telegram. It contains this text:
<said from="Leo">Book Luigi's for 7 tonight, and text Maren so she knows.</said>

# Understanding
<understanding from="the system" cites="M2 M5">Leo asks for two things: a table at Luigi's, his usual Italian place, at 7 pm tonight, Thursday 30 October, and a text to Maren, his partner, telling her about it. He gives no party size.</understanding>
<unclear from="the system" gap="how many people the table is for">
  <reading from="the system">two: Leo and Maren</reading>
  <reading from="the system">more, if others are coming</reading>
</unclear>
- Belongs to: nothing yet; it starts something new.

# Knowledge

## The situation
- Now: Thursday 30 October 2026, 5:40 pm, in Leo's time zone (Europe/Lisbon). Every time below is in this zone.
- Leo's last stimulus: Thu 30 Oct 2026, 3:32 pm, on Telegram.
- The origin: Leo's Telegram chat with the system, where a reply can be written.

## Stimulus origin knowledge
Telegram gives the system no history of this chat; what it saw here is under stimulus origin memory.

## Concurrent stimuli
Nothing else is running.

# Memory

## Always in mind
- Leo is the one the system serves, and calls it Aether.
- <memory label="M1" from="the system" pinned="yes">Maren is Leo's partner.</memory>

## Short-term memory
Nothing else recent: the only recent work is shown under stimulus origin memory.

## Long-term memory
### Recalled memories
<memory label="M2" from="the system" kind="something Leo said" learned="Sun 18 Oct 2026, 7:02 pm">Luigi's is Leo's usual Italian place.</memory>

### Matters
Nothing came to mind.

## Stimulus origin memory
<episode label="E1" origin="Telegram" at="Thu 30 Oct 2026, 3:32 pm" ended="completed">
  <input><said from="Leo">Remind me to call the plumber tomorrow</said></input>
  <understood from="the system">Leo asks to be reminded tomorrow, Friday 31 October, to call the plumber. He names no time.</understood>
  <did from="the system">set_reminder: Friday 31 October, 9:00 am, "call the plumber", for Leo. Set.</did>
  <did from="the system">text to Leo, by Telegram: "I'll remind you tomorrow at 9." Delivered.</did>
</episode>
```

The report after round 1, whose only call was a booking, carries the booking's result under
the call's id and then the news, where Leo has written again:

```text
result for toolu_01: Not booked: no table for 2 at 7:00 pm tonight. Open: 6:30 pm and 7:45 pm.

Since the last round:
<stimulus label="E2" origin="Telegram" at="Thu 30 Oct 2026, 5:41 pm" offered="yes">
  <said from="Leo">oh and make it 3, my sister's coming</said>
  <understood from="the system">The Luigi's table should be for three, since Leo's sister is joining.</understood>
</stimulus>
```

The example predates two clauses, and where they differ the clauses rule: the result carries
its `R` label where ADR-0307 §5:1 gives one (§5:4), and what each tool's result says is
The tools decision's.

## Consequences

**What gets easier.**
- **Planning sees its own rounds.** It reads what it wrote and what came of it as it was
  written, and is not re-told the whole context each round.
- **The exchange caches.** Tools and instruction are the same for every work, and the
  briefing for every round of one, so a round costs little more than what changed. The round
  after each message, which the tools decision's design adds, is cheap for that reason.
- **One instruction.** No flag and no conditional part, so one text is reviewed,
  overridden and replayed, and an empty section says why.
- **Silence is the default.** A round writes to no one unless it calls a message tool, so a
  reply can wait for the results it reports.
- **Later work knows what was done.** The short view shows each call that changed something,
  with its result, so "was the email sent?" is answered from the record.
- **No reserved tool.** The notes are the model's own text, and nothing in the request is a
  tool that runs nothing.

**What gets harder, and what this leaves.**
- **A reply written as text reaches no one.** It is the risk §7 accepts, and the first suite
  case measures it. The fallback, a notes tool with stray text sent back as news, needs a
  decision of its own.
- **A model may write little text.** Some models return the text they write between calls
  as thinking, so a work's notes may be short or empty; the short view then shows its calls
  alone.
- **Four lanes and the tools decision's message tools deploy together.** P1 removes the notes and the
  naming from the response, and planning cannot speak until the message tools exist, so no
  release carrying P1 reaches a hub before the rest (§14:11).
- **The episode grows.** Every call's entry is recorded, and the diagnostic record holds the whole
  exchange with each round's given entry.
- **The live override goes at the deploy,** by the owner's act or direction (§11:7).
- **The new default skips ADR-0337's three days.** No override can run it before the code
  exists, so it is judged on the suite and then live.
- **On a spoken pass, a short view shows little.** Entries are placed for the owner alone, as
  notes are, so where those may not be shown, other work is seen by its input, meaning and
  ending.

- **Outside content beyond a paste.** The owner's direction on #3515 goes further than its
  ruling: "I think that planning can see outside content and relaying, as long as there is
  the proper mark for it, and then we can restrict what it can do based on the mark with the
  actual tools … more of this will be thought through in the audience privacy authority
  design tho". This decision takes only the paste (§3:7); the rest is that design's to
  decide.

**What would reopen it.** The suite showing replies written as text; a provider that cannot
take an appended exchange; or a reader that needs a call's entry placed by audience.

## Alternatives considered

- **Keep each round asked afresh.** It keeps the view current and never replays a tool turn
  in a provider's own form. Not chosen: planning loses sight of its rounds and nothing
  caches past the instruction. §5 keeps the view current by sending changes as news.
- **A notes tool, with text given no use.** Any text is then a mistake that can be caught:
  dropped and sent back as news, with one more round so a lost reply gets its chance. Not
  chosen: once the system is the briefer, bouncing planning's reply to that system is odd,
  and the mistake is less likely. Kept as the fallback if the suite shows replies written as
  text.
- **Keep the last note only in the short view.** Not chosen: with text as notes, the last
  text is often empty or "done". The owner: "maybe it should see all of it… not that much".
- **Show whole episodes.** Not chosen: they are large, bring back forgotten memories through
  old results, and show stale results as current. The short view and the look-up split it.
- **Offer tools by round.** Not chosen: a varying set breaks the cache at its first byte and
  needs a conditional instruction. A call that cannot run comes back saying why.
- **Model each provider's thinking in `core`.** Not chosen: providers differ, and `core`
  should name none of them. The continuation is opaque, and only `models/` reads it.
- **Rebuild the exchange from the episode each round.** Not chosen: the episode keeps no
  thinking, so the provider would reject or lose it, and the briefing would be re-rendered
  rather than handed back byte for byte.
- **Read what came of a call from the plan store's effect records.** Not chosen: a look-up
  or a refused call has no effect record, and the short view is a selection of the episode's
  own parts, so the episode records one entry per call.
- **Record each round's report whole.** Not chosen: a held result is never saved
  (ADR-0308 §6:4), and the look-up keeps what a call showed by reference, not by copy (the
  memory decision). One entry per call holds the outcome both views need.
- **Put the offers in the briefing on every round.** Not chosen: re-rendering the briefing
  breaks the cache and repeats what was shown. An offer open at the first round is in the
  briefing, and every later one is news.
