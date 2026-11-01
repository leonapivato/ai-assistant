# 322. A reply may approve several questions, each under its own approval, and understanding sees which messages are questions

- Status: Partially superseded by ADR-0353 (§2:1–§2:7, whole; §4:1, §4:2 and §4:4–§4:9, whole; each until a later decision: understanding is shown no mark and records no pointer) and ADR-0361 (§3 and §4:3, whole: no question is marked or approved)
- Date: 2026-10-15
- Scope: the authority milestone, M44 ([milestone #11](https://github.com/leonapivato/ai-assistant/milestone/11)), acceptance [#3058](https://github.com/leonapivato/ai-assistant/issues/3058), batch [#3059](https://github.com/leonapivato/ai-assistant/issues/3059): how many questions one reply may approve, and how understanding tells a question from a message that only asked in words.
- Dependency: [ADR-0321](0321-authority-at-the-deploy-is-your-yes-to-a-question-that-showed-the-call.md), Accepted, and the yes path its lanes built, on `main` at `8257e6fa`.
- Authorization: the owner's two rulings of 2026-10-15, given to the dispatcher after #3058's re-run: on [#3075](https://github.com/leonapivato/ai-assistant/issues/3075), "why can one reply only authorize one thing?", then "go ahead"; and on [#3072](https://github.com/leonapivato/ai-assistant/issues/3072), "yes, fold it in". The dispatcher assigned 0322, and on this draft's first review settled two details the rulings leave open: the mark is read through `project_episode`, and each question carries a label of its own that a pointer names it by (§4:3–§4:6).
- **Changes `core`, so it is a contract-surface decision.** `ProposedActivationUnderstanding` and `ActivationUnderstanding` carry a sequence of answer pointers in place of one, and `project_episode`'s projected round gains the parts its message asked about. Both cross the wire, so `PROTOCOL_VERSION` advances (§6).
- **Partially supersedes**, each in the scopes §7 states:
  [ADR-0321](0321-authority-at-the-deploy-is-your-yes-to-a-question-that-showed-the-call.md) (§3:1's one pointer, §3:2 in the addition alone, §3:6 per question, and §9's two understanding rows),
  [ADR-0276](0276-an-activation-is-understood-before-it-is-associated-and-the-understanding-is-retained-with-its-episode.md) (§3:3's label scheme and §2:1's field sets, in the additions alone) and
  [ADR-0284](0284-an-episode-is-the-experience-of-processing-its-activation.md) (§8:1's projection, in the addition alone).
- Partially superseded: 2026-10-27 by ADR-0353 — §2:1–§2:7, whole; §4:1, §4:2 and §4:4–§4:9, whole; each until a later decision redesigns approvals: understanding is shown no question mark and no `Q` label, and records no pointer (ADR-0353 §11). §4:3's projection of a round's asked parts stands. Every other clause stands. This replacement takes effect on ratification of ADR-0353. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; the ratified body below is preserved.
- Partially superseded: 2026-10-31 by [ADR-0361](0361-approvals-are-cards-the-person-taps-and-a-yes-is-a-one-time-ticket-for-the-exact-call.md) — §3 and §4:3, whole: no input approves anything, so no reply's approval is assembled and a projected round carries no asked parts (ADR-0361 §4:11, §8:5). Every other clause stands. This replacement takes effect on ratification of ADR-0361. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.

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

**What the first review found.** Every rendering of a stored episode reads it through
`project_episode` and renders no other field (ADR-0284 §8:3), so a mark read from the rounds
must ride the projection. And a story is shown under one `S` label whose episodes take none
(ADR-0300 §6:5), so two questions seen only through a story could not be named apart.

## Decision

We will let one reply approve several questions, each by its own pointer and under its own
approval, and mark and label for understanding every message that is a question.

### 1. Status and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree.

> **Normative.** No lane implements this decision until it has merged `Accepted`. Its code
> lane is cut then, under batch #3059.

### 2. Several questions

> **Normative.** Where an input approves, understanding records one pointer per question it
> approves, each naming that question by its label (§4:4) and the parts of it the input
> approves, and no question twice.

> **Normative.** A reply approves several questions only where it says which: "both", "all
> of them", naming them, or naming them in reply to a message that asked which was meant. The
> pointers name the questions, never the message that asked which.

> **Normative.** ADR-0321 §3:5 stands: a bare yes that could fit more than one question
> records no pointer and gets "yes to which?", never a guess.

> **Normative.** A yes approves every part each question it names showed, and a partial yes
> approves only the parts it names, question by question.

> **Normative.** Each pointer is a reading and grants nothing by itself (ADR-0276 §7:7).

> **Normative.** Each pointer resolves on its own. One that §4:5 does not admit, or that
> names a part its question did not show, is not recorded, and the understanding gains the
> code-owned unresolved matter saying so; the others stand.

> **Normative.** Where two proposed pointers name one question, neither is recorded, and the
> understanding gains the code-owned unresolved matter saying so.

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

### 4. Questions are marked and labelled

> **Normative.** Code marks, in what understanding is shown, each message that is a question:
> one whose round recorded asked calls (ADR-0321 §2:8), with the parts it showed. A message
> that asked only in words carries no mark.

> **Normative.** The mark is carried wherever understanding is shown a question: on its
> message in the place window, and on the round that asked it in an episode shown in the
> episode window, in the recalled section or in a story's short view.

> **Normative.** Every mark is read through `project_episode`: a projected round carries the
> part numbers its message asked about, and no values, derived from the round's recorded
> asked calls and never from a message's text (ADR-0284 §8:3, ADR-0276 §3:6). It carries
> them only where it carries the round's message.

> **Normative.** Each marked question carries a label of its own: the ASCII string `Q`
> followed by its 1-based index in decimal with no padding, on ADR-0276 §3:3's scheme, in
> the order the questions are first rendered. A question rendered in more than one place
> carries one label, and no label survives the call.

> **Normative.** A pointer names its question by its `Q` label and by no other. A pointer
> naming another label, or a `Q` label the call did not render, is not recorded (§2:6), so a
> yes never lands on an unmarked message.

> **Normative.** A `Q` label names no referent. Anywhere in a proposal but a pointer, it is
> a label naming nothing (ADR-0276 §3:4).

> **Normative.** The mark is information for understanding's reading. It approves nothing,
> and the three facts still decide (ADR-0321 §4:4).

> **Normative.** The mark says that a message is a question and which parts it showed, and
> never whether it was answered. ADR-0321 §3:2's *nothing lists unanswered questions* and
> §3:10's *nothing opens or closes it* stand.

> **Normative.** Understanding's instruction says what the mark and the `Q` label mean, that
> a pointer names a question by its `Q` label alone, and when one reply approves several
> questions (§2:2).

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
| `ProposedActivationUnderstanding` | `answers` becomes a sequence of `ProposedAnswer`, each naming a `Q` label, empty where the input approves no question |
| `ActivationUnderstanding` | `answers` becomes a sequence of `AnsweredQuestion`, naming no question twice |
| `ProjectedRound`, through `project_episode` | Gains the part numbers its message asked about, where it carries the message (§4:3) |
| `orchestration/understanding.py` | The marks and the `Q` labels (§4:1–§4:6); several pointers, each resolved on its own (§2:6–§2:7); the instruction (§4:9) |
| `orchestration/authorizer.py` | The yes's context carries every pointer, and an approved call is checked against the one whose question asked it (§3:1, §3:3) |
| `orchestration/phase_path.py` | The approved actions are gathered from every pointer (§3:4) |
| `Approval`, `PermissionDecision`, `ActivationEffect`, `PlanStore.claim_activation_effect` | Unchanged |

> **Normative.** The `core` types change as the table states; their exact shapes are the code
> lane's, within the table.

> **Normative.** The change advances `PROTOCOL_VERSION` on ADR-0124 §9's rule, and the deploy
> starts from a fresh data directory, so nothing stored with a single pointer is read.

### 7. Relationship to earlier decisions

| Earlier decision | What changes |
| --- | --- |
| ADR-0321 §3:1 | Its one pointer: one per question the input approves, named by its `Q` label (§2:1, §4:5) |
| ADR-0321 §3:2 | In the addition alone: questions are marked and labelled (§4). *Nothing lists unanswered questions* stands |
| ADR-0321 §3:6 | Per question: a yes approves every part of each question it names (§2:4) |
| ADR-0321 §9's `ProposedActivationUnderstanding` and `ActivationUnderstanding` rows | The pointer becomes a sequence (§6) |
| ADR-0321 §3:5, §3:10, §4 | Nothing: §2:3, §4:8 and §3 apply them per question |
| ADR-0276 §3:3 | In the addition alone: a fifth sequence, `Q`, for questions (§4:4) |
| ADR-0276 §2:1 | `ProposedActivationUnderstanding`'s and `ActivationUnderstanding`'s field sets, in ADR-0321's addition alone: the pointer becomes a sequence. §7:7's *grants no authority* stands |
| ADR-0284 §8:1 | The projection, in the addition alone: a projected round carries the parts its message asked about (§4:3). §8:3 stands, and the mark is read through it |
| ADR-0300 §6:5 | Nothing: the episodes in a short view still take no label; a question shown in one takes a `Q` label, which names no referent (§4:6) |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0321, ADR-0276 and ADR-0284, atomically with this ADR under
> ADR-0070 and ADR-0082, preserving their ratified bodies. The replacements take effect on
> this ADR's ratification.

## Consequences

- "Both", "all of them" and a change that adds to a waiting call can be approved in one
  reply, and each call still runs only under its own question's approval, once.
- A yes can no longer land on a prose copy: a pointer names a `Q` label or records nothing,
  and planning can ask which was meant.
- Understanding's prompt grows by one mark and one label sequence, and its instruction by
  one paragraph.

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
- **Pointers keep naming the message's or episode's label, and a label holding several
  questions records none.** Rejected: "both" would stay unanswerable for questions seen only
  through a story.
