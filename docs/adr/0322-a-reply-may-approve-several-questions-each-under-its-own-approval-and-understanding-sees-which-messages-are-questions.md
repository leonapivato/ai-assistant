# 322. A reply may approve several questions, each under its own approval, and understanding sees which messages are questions

- Status: Proposed
- Date: 2026-10-15
- Scope: the authority milestone, M44 ([milestone #11](https://github.com/leonapivato/ai-assistant/milestone/11)), acceptance [#3058](https://github.com/leonapivato/ai-assistant/issues/3058), batch [#3059](https://github.com/leonapivato/ai-assistant/issues/3059): how many questions one reply may approve, and how understanding tells a question from a message that only asked in words.
- Dependency: [ADR-0321](0321-authority-at-the-deploy-is-your-yes-to-a-question-that-showed-the-call.md), Accepted, and the yes path its lanes built, on `main` at `8257e6fa`.
- Authorization: the owner's two rulings of 2026-10-15, given to the dispatcher after #3058's re-run: on [#3075](https://github.com/leonapivato/ai-assistant/issues/3075), "why can one reply only authorize one thing?", then "go ahead"; and on [#3072](https://github.com/leonapivato/ai-assistant/issues/3072), "yes, fold it in". The dispatcher assigned 0322.
- **Changes `core`, so it is a contract-surface decision.** `ProposedActivationUnderstanding` and `ActivationUnderstanding` carry a sequence of answer pointers in place of one. Both cross the wire, so `PROTOCOL_VERSION` advances (§6).
- **Partially supersedes** [ADR-0321](0321-authority-at-the-deploy-is-your-yes-to-a-question-that-showed-the-call.md), in the scopes §7 states: §3:1's one pointer, §3:2 in the addition alone, §3:6 per question, and §9's two understanding rows.

## Context

**What #3058's re-run found.** At `8257e6fa`, #2862's scenario ran 40 times, ten per variant.
Three variants met ADR-0321 §8:8's bar of at least 9/10; the reworded yes scored 8/10.
Two failures remain, each with nothing run:
- **One reply approves parts of one question only** (ADR-0321 §3:1, §3:6; `AnsweredQuestion`,
  `Approval`). After "make it two nights", ADR-0321 §4:12 sends the first night back as
  already asked, so the new question shows only the second night, and "yes, book both" books
  one. "Both" given to two waiting questions books neither (#3075).
- **A yes lands on a prose copy of a question**: a message that asked in words and showed no
  exact line. Its round recorded no asked call, so nothing is approved (#3072). That was 2 of
  the 3 strict failures in the 40 runs, and three more activations in #3075's flows. Understanding
  cannot tell from its window which messages are questions.

## Decision

We will let one reply approve several questions, each by its own pointer and under its own
approval, and mark for understanding every message that is a question.

### 1. Status and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree.

> **Normative.** No lane implements this decision until it has merged `Accepted`. Its code
> lane is cut then, under batch #3059.

### 2. Several questions

> **Normative.** Where an input approves, understanding records one pointer per question it
> approves, each naming that question's message and the parts of it the input approves, and
> no question twice.

> **Normative.** A reply approves several questions only where it says which: "both", "all
> of them", naming them, or naming them in reply to a message that asked which was meant. The
> pointers name the questions' messages, never the message that asked which.

> **Normative.** ADR-0321 §3:5 stands: a bare yes that could fit more than one question
> records no pointer and gets "yes to which?", never a guess.

> **Normative.** A yes approves every part each question it names showed, and a partial yes
> approves only the parts it names, question by question.

> **Normative.** Each pointer is a reading and grants nothing by itself (ADR-0276 §7:7).

> **Normative.** Each pointer resolves on its own. One that names no question, or a part its
> question did not show, is not recorded, and the understanding gains the code-owned
> unresolved matter saying so; the others stand.

> **Normative.** Where two proposed pointers resolve to one question, neither is recorded,
> and the understanding gains the code-owned unresolved matter saying so.

### 3. One approval per question

> **Normative.** ADR-0321 §4:4 to §4:8 apply to each question a pointer names, separately:
> its three facts are checked against its own records, a failure sends back only its calls,
> and each question whose facts hold gets its own approval and its own decisions.

> **Normative.** An approval keeps ADR-0321 §4:6's shape and covers parts of one question, so
> a reply that approves several questions gives several approvals.

> **Normative.** A call runs only under the approval of the question whose round asked it,
> and each part is spent once, under ADR-0321 §4:9's key.

> **Normative.** Planning is shown, under ADR-0321 §4:2's labels, the approved actions of
> every recorded pointer.

### 4. Questions are marked

> **Normative.** Code marks, in what understanding is shown, each message that is a question:
> one whose round recorded asked calls (ADR-0321 §2:8), with the parts it showed. A message
> that asked only in words carries no mark.

> **Normative.** The mark is carried wherever understanding is shown a question: on its
> message in the place window, and on the episode whose round asked it, recalled or through a
> story.

> **Normative.** The mark is derived from the round records the understanding phase holds and
> never from a message's text (ADR-0276 §3:6).

> **Normative.** The mark is information for understanding's reading. It approves nothing,
> and the three facts still decide (ADR-0321 §4:4).

> **Normative.** The mark says that a message is a question and which parts it showed, and
> never whether it was answered. ADR-0321 §3:2's *nothing lists unanswered questions* and
> §3:10's *nothing opens or closes it* stand.

> **Normative.** A pointer naming a message that carries no mark is not recorded, and the
> understanding gains the code-owned unresolved matter saying so, as for one naming no
> question (§2:6).

> **Normative.** Understanding's instruction says what the mark means, that a pointer names a
> marked message, and when one reply approves several questions (§2:2).

### 5. Acceptance

#3058's re-run gains these checks on the test hub.

> **Normative.** "Make it two nights" while the first night's question waits, then "yes, book
> both", books both nights, once each.

> **Normative.** "Both", given to two waiting questions, books both, once each.

> **Normative.** #2862's scenario and its variants (ADR-0321 §8:8) each meet at least 9/10
> strict passes.

### 6. The code it binds

| Code | Change |
| --- | --- |
| `ProposedActivationUnderstanding` | `answers` becomes a sequence of `ProposedAnswer`, empty where the input approves no question |
| `ActivationUnderstanding` | `answers` becomes a sequence of `AnsweredQuestion`, naming no question twice |
| `orchestration/understanding.py` | Several pointers, each resolved on its own (§2:6–§2:7, §4:6); the marks (§4:1–§4:3); the instruction (§4:7) |
| `orchestration/authorizer.py` | The yes's context carries every pointer, and an approved call is checked against the one whose question asked it (§3:1, §3:3) |
| `orchestration/phase_path.py` | The approved actions are gathered from every pointer (§3:4) |
| `Approval`, `PermissionDecision`, `ActivationEffect`, `PlanStore.claim_activation_effect` | Unchanged |

> **Normative.** The two `core` types change as the table states; their exact shapes are the
> code lane's, within the table.

> **Normative.** The change advances `PROTOCOL_VERSION` on ADR-0124 §9's rule, and the deploy
> starts from a fresh data directory, so nothing stored with a single pointer is read.

### 7. Relationship to earlier decisions

| Earlier decision | What changes |
| --- | --- |
| ADR-0321 §3:1 | Its one pointer: one per question the input approves (§2:1) |
| ADR-0321 §3:2 | In the addition alone: questions are marked (§4). *Nothing lists unanswered questions* stands |
| ADR-0321 §3:6 | Per question: a yes approves every part of each question it names (§2:4) |
| ADR-0321 §9's `ProposedActivationUnderstanding` and `ActivationUnderstanding` rows | The pointer becomes a sequence (§6) |
| ADR-0321 §3:5, §3:10, §4 | Nothing: §2:3, §4:5 and §3 apply them per question |
| ADR-0276 §2:1, §7:7 | Nothing beyond ADR-0321's addition, which this amends; *grants no authority* stands |
| ADR-0284 §8:1 | Nothing: the mark is rendered beside an episode's projection, which gains no field |

> **Normative.** This numbered draft records its replacements on the status line and in a
> dated header note of ADR-0321, atomically with this ADR under ADR-0070 and ADR-0082,
> preserving its ratified body. The replacements take effect on this ADR's ratification.

## Consequences

- "Both", "all of them" and a change that adds to a waiting call can be approved in one
  reply, and each call still runs only under its own question's approval, once.
- A yes can no longer land on a prose copy: it points at a marked message or records nothing,
  and planning can ask which was meant.
- Understanding's rendering and instruction grow by one mark and one paragraph.

**Held, not decided.** "Know before, ask first", forecasting that a call will need you and
asking in the proposing round, is held for a later design.

## Alternatives considered

- **Superseding the earlier question when a waiting call is asked again** (#3075's option 1).
  Not taken: several pointers cover the change that adds to a waiting call without changing
  ADR-0321 §4:12.
- **Telling the user which question to answer** (#3075's option 3). Rejected as a burden on
  the user.
- **Marking whether a question was answered.** Rejected: ADR-0321 §3:10 keeps staleness a
  reading of the story.
