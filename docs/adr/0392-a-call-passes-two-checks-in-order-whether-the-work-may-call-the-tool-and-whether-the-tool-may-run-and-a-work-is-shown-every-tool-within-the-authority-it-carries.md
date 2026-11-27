# 392. A call passes two checks in order, whether the work may call the tool and whether the tool may run, and a work is shown every tool within the authority it carries

- Status: Proposed
- Date: 2026-11-27
- Scope: the amending decision from rows 2 and 3 of the third round of the owner's review of
  ADR-0365 to ADR-0372, of 2026-11-27: the two checks on a call and their cards (§2), what a card to
  the person whose work it is cannot do (§3), which tools a work is shown (§4), the owner's worked
  case (§5), earlier decisions (§6), what is built and what building needs (§7, §8), what is left
  (§9), and whose each point is (§10).
- Authorization: the owner's rulings of 2026-11-27 in the review's third round, quoted verbatim in
  §10 with where each is recorded. The rest is the coordinator's proposal, ratified by the
  coordinator under the owner's delegation once its reviews are green.
- **Contract-surface decision; a decision only.** It changes no Protocol, type, field or code, and
  bounds what the check asks and what a work is offered, so it takes the adversarial and the
  architecture review. Building it needs no `core` change of its own (§8).
- **Partially supersedes** ADR-0367 (§4:6's last sentence), ADR-0368 (§8's *could use*) and
  ADR-0391 (§3:3, in the addition alone), each in the scope §6 gives.

## Context

ADR-0367 §4:1 checks every call against lines for the person whose authority a work carries;
ADR-0391 §3:2 runs it for everyone in the work's say, at the level of its context (ADR-0371 §6:2),
and ADR-0379 §2 gives its outcome. Two outcomes need a yes: a shortfall, whose card goes to the
person whose authority the work carries (ADR-0367 §5:3), and a grant that asks, which needs the yes
of whoever the call's thing belongs to (ADR-0367 §5:6, ADR-0381 §6). ADR-0391 §3:3 sends the first
of those cards also where another in the say is the reason a call is not allowed. ADR-0367 §4:6
keeps ADR-0021 §5's floor: a disclosing call only a default grant allows goes to approval. ADR-0368
§8 offers a work only what its authority **could use**, fixed at its first round (§8:1).

The review put to the owner that a message to a hub person allowed only by its default grant
(ADR-0367 §12:1) may take a card each time (the scenarios document's GAP-01). The owner found it
backwards, and ruled two checks on a call, in order, and which tools a work is shown (§10).

**Words.** A line, grant, limit, bar, level, the check, a card and a yes are ADR-0367's; a grant
**allows** or **asks** as ADR-0379 has it; a say is ADR-0391's and the mark ADR-0370's. The **first
card** is §2:2's, the **second card** §2:4's, and a work's **ceiling** §4:1's. A bare section
reference, such as §2:1, is to this decision.

## Decision

We will check a call in two steps, in order, whether this work may call the tool and then whether
the tool may run, and show a work every tool within the authority it carries.

### 1. Status, scope and delivery

> **Normative.** No lane implements against this decision before it merges `Accepted` (golden
> rule 5, ADR-0015 §5).

> **Normative.** This decision dispatches no implementation, and until it is built nothing in it
> changes what the running hub allows, asks, offers or shows.

### 2. Two checks on a call, in order

> **Normative.** The check (ADR-0367 §4:1) asks two things of a call, in this order. First, may this
> work call the tool at its current authority: whether a grant covering the call applies for each
> person in its say, at the level of its context. Second, may the tool run: whether the grant that
> applies allows the call or asks.

> **Normative.** Where the first falls short only because the level of the work's context is below
> a covering grant's bar (ADR-0367 §5:3, ADR-0379 §2:5), or because another in its say may not make
> the call (ADR-0391 §3:3), the call needs the **first card**, to the person whose authority the
> work carries.

> **Normative.** A call short on both grounds takes one first card, at the bar ADR-0379 §2:5 gives
> for that person: its ticket's call is checked for the tapper alone, at the tap's level (ADR-0367
> §5:5).

> **Normative.** Where the second asks, a grant that asks applying and none that allows (ADR-0379
> §2:4), the call needs the **second card**, to the person the permission names: whoever the call's
> thing belongs to, by its record (ADR-0367 §5:6, ADR-0381 §6:1), or, for a call with no thing, the
> person ADR-0381 §6:2 names. Neither a grant's who nor who set it names whom to ask.

> **Normative.** A call that needs both cards takes the first before the second: ADR-0379 §2:5
> counts a grant that asks alike, so at a level at which no covering grant applies the outcome is a
> shortfall, and the first card's ticket, checked again, comes back needing the second as a new
> request (ADR-0367 §5:5 and §5's note).

> **Normative.** Both checks are the one check ADR-0367 §4:5 puts first among ADR-0306 §4:1's; the
> policy, the outside-content stand-in and the place follow as merged. The mark checks every send
> beside them (ADR-0370 §5:1, ADR-0391 §6:1), and where it and the check both need a yes, the mark's
> is asked first (ADR-0370 §5:8).

The order is the merged one: §2:5 states what ADR-0379 §2 and ADR-0367 §5's note already give.
Each card covers its one call: a yes is a ticket for the exact call, used once (ADR-0361 §5:1,
§5:5), checked for its tapper (ADR-0367 §5:5), and no merged clause raises a work's level or say on
a tap (ADR-0368 §2:5, ADR-0391 §3:1). Whether a yes on one card covers another is ADR-0370 §5:5's,
as merged. This decision adds nothing to either.

### 3. A card to the person whose work it is

> **Normative.** A call that no grant covers for the person whose authority the work carries, or
> that a limit covers for them, is not done and asks no one (ADR-0367 §4:2), save the card ADR-0367
> §6:3 sends to the person whose own account it would act through: no card to the person whose
> authority the work carries stands in for a grant they lack.

> **Normative.** No card to the person whose authority a work carries makes a call allowed beyond
> what the lines allow that person at the tap's level (ADR-0367 §5:5, §10:3), and none stands in
> for a second card that names someone else (§2:4, ADR-0381 §6:1).

> **Normative.** A `text` call to a person the hub admits, into their own chat (ADR-0367 §12:1),
> takes no card for being allowed by a default grant alone: ADR-0367 §4:6's last sentence does not
> reach it, and every other check it passes stands.

The first card is no card to oneself in the owner's sense: it brings the work back up to its
person's own authority, which a fall in its level (ADR-0371 §6:1) or its say (ADR-0391 §3:1) took
it below, and never above it. ADR-0367 §5:3's card and ADR-0391 §3:3's stand, the latter as §2:3
adds to it. A second card that names the work's own person, for a call with no thing or a thing of
theirs, is the second check: their own grant asks, and the yes lifts nothing.

No policy rules a `text` call in the merged texts (ADR-0356 §7:7, as ADR-0367 §4:7 and ADR-0391 §6:1
amend it), and the built authorizer hands none to the policy, so ADR-0021 §5's floor never reached
one. §3:3 closes the reading of ADR-0367 §4:6 that had it ask (GAP-01). ADR-0021 §5 stands whole: a
disclosing call the policy rules, such as `send_email`, under a default line alone, still goes to
its person's yes (ADR-0379 §3).

### 4. Which tools a work is shown

> **Normative.** A work's **ceiling** is the authority it carries (ADR-0368 §2:2), at its sureness
> (ADR-0368 §2:3): the lines that apply to that person, or to each of its senders (ADR-0368 §7:3),
> with no one else in its say counted.

> **Normative.** ADR-0368 §8's *could use* reads the ceiling: a tool, a connection or a person is
> one the work's authority could use where some call on it could be allowed for the ceiling by the
> check, by the first card, by the second card, or under a ticket the work holds (ADR-0367 §5:5), or
> where the check would not reach it, as ADR-0368 §8 has it.

> **Normative.** A fall in the level of the work's context (ADR-0371 §6:1) or in its say (ADR-0391
> §3:1) hides nothing and shows nothing: the set ADR-0368 §8:1 fixes stands for the work, and a call
> the work no longer reaches takes the first card, where the work may ask (ADR-0368 §7:4).

> **Normative.** A tool a grant lets the ceiling's person only ask for is shown, and its call takes
> the second card.

> **Normative.** A tool on which no call could be allowed in any of §4:2's ways is not shown: one
> no grant covers for the ceiling, or a limit covers, or whose yes is no one's (ADR-0381 §5:2,
> §6:3) or cannot be asked in that work (ADR-0368 §7:4), where the work holds no ticket that could
> run a call of it and the check reaches it.

ADR-0368 §8:2 and §8:3 read *could use* as §4:2 has it, and ADR-0368 §8:4 to §8:6 stand. Its "at
its level" was the sureness ADR-0368 §2:3 records, which §4:1 keeps.

### 5. The owner's worked case

The owner's words, verbatim: "The model sees only the tools that are within the ceiling of
authority for that work. This is what the first card does and it answer the question, can this tool
even be called. Then there is can this tool even be run, which is where it may ask for permission.
So for the text Sam case, lets say Sam is the owner. I ask the assistant to text sam and to search
something up. Now it gets all of the tools under the authority ceiling, which is just my authority.
Then it does the web search, lowers the authority score, now when it tries to do the text sam tool
call, it send me a card to raise it back to high enough authority. Than it runs the tool call. Sam
has it setup that my authority isnt high enough to run the tool call, but it high enough to ask for
permission, so it sends a card to same to get the remaining authority. Sound good"

In this corpus's terms, with Sam the owner and the speaker a person the hub admits: the work carries
the speaker's authority, so the search and the text are both offered (§4:1, §4:2). The search lowers
the level of the work's context (ADR-0371 §6:1), and the text into Sam's chat then falls short of
its covering grant's bar: the first card, to the speaker (§2:2). On that tap the ticket's call is
checked for the speaker at the tap's level, and Sam's line on his chat, a grant that asks applying
for the speaker, decides it: the second card, to Sam, whose chat it is (§2:4). On Sam's yes it runs
under its ticket (ADR-0361 §5, ADR-0367 §5:5), and the mark checks the send throughout (§2:6).

### 6. Relationship to earlier decisions

> **Normative.** This numbered draft records its replacements on the status lines of ADR-0367,
> ADR-0368 and ADR-0391 and in a dated header note on each, atomically with this ADR under ADR-0070
> and ADR-0082, preserving their ratified bodies. The replacements take effect on this ADR's
> ratification.

| Clause | Becomes |
| --- | --- |
| ADR-0367 §4:6's last sentence, the floor for a disclosing call only a default grant allows | In its reach alone: not a `text` call to a person the hub admits, into their own chat (§3:3) |
| ADR-0368 §8's *could use*, read by §8:1 to §8:3 | Read at the ceiling, counting the second card; a fall in level or say changes nothing offered or shown (§4) |
| ADR-0391 §3:3's last sentence, a call not allowed for those whose authority the work carries | In the addition alone: one short on both grounds takes one first card (§2:3) |

Read through and standing: ADR-0367 §4:1, §4:2, §4:5, §5:1 to §5:6, §10:3, §12:1 and §16; ADR-0379
§2 to §4; ADR-0381 §5 and §6; ADR-0391 §3:2, §3:5 and §6; ADR-0370 §5; ADR-0371 §6; ADR-0361 §5;
ADR-0368 §7; and ADR-0021 §5 and §6, whose standing grant stays the way a disclosing call the policy
rules stops asking.

### 7. What is built today, and what becomes of it

| Built | Cites | Becomes, once built |
| --- | --- | --- |
| `_a_card_could_ask` in `orchestration/could_use.py`: a grant that asks is one a work could use only where its yes is the work's person's | ADR-0367 §5:6, ADR-0381 §6 | Also where it is another's (§4:4) |
| `_yes_needed` in `orchestration/authorizer.py`: such a call not done, no one asked | ADR-0367 §16's approvals change, not built | The second card, to that person (§2:4) |
| `_call_message` there and `_NEVER_ASKED` in `could_use.py`: a `text` call needing a yes is not sent, and never asked about | ADR-0356 §7:7 | Takes the first and second cards as any call does (§2), as ADR-0391 §6:5 already has a reply take the first |
| The offered set and the Connections, weighed for the check's subject as the round is handed it | ADR-0368 §8:1, §8:2 | Weighed for the ceiling (§4:1); the same today, since that subject is the authority carried, at the sureness |

For one owner on their own chats, nothing changes once built: every record names the owner
(ADR-0381), so no second card names another person, and under today's default lines no `text` call
in the owner's work needs a yes.

### 8. What building it needs

Named so the build is scoped, and made by none of this decision. It needs no contract, store,
format or wire change of its own.

- **Approvals:** the second card to a person other than whom the asking work is for is ADR-0367
  §16's approvals change, with §15's rows on ADR-0361 §2:6, §4:2 and §4:6, built with a second
  person (ADR-0367 §1:4).
- **Orchestration:** `_a_card_could_ask` and `_yes_needed` counting another person's yes (§2:4,
  §4:4); `send_text` asked about as any call (§2); the offered set and the Connections weighed for
  the ceiling once ADR-0371 §6 or ADR-0391 §3 makes the check's level or say differ from it (§4:1).

### 9. What this decision leaves to others

- **The owner:** the record's three picks not ruled, among them whether the sender's card also
  covers the mark's (ADR-0370 §5:5 and §5:8 stand); whether ADR-0021 §5's floor card, on a disclosing
  call the policy rules that only a default allows, is a card the owner's rule on a card to oneself
  reaches; every bar.
- **A later decision:** rows 1 and 4 to 6 of the record and every group ruling; ADR-0391 §10's two
  points; how a work that is no person's asks (ADR-0368 §7:4).
- **The next prompt review:** how each card's outcome is worded to a model (ADR-0367 §3:7).

> **Normative.** This decision may not be cited to settle any matter the list above leaves to
> another.

### 10. Whose each point is

The owner's words are verbatim, from the local record of the review, by line: `review-log.md`,
"Round 3", and its summary `review-addition-round-3.md`, quoted with their line breaks joined.

| Point | The owner's words | Where |
| --- | --- | --- |
| Two checks in order, and whose each card is (§2) | "I would frame it like this. The first check is can this tool even be called with the current authority. Thats the card to the person whose work is currently be run. Then there is can the tool even be run, which is the ask permission to x person. Right?"; then "Yes send it" | review log, lines 270 to 275; summary, line 11, from "The first" to "x person." |
| Two kinds of authority on one call (§2) | "there are different permissions here. For the text sam case, there is my authority and whether it reaches the threshold to even do that. Like if it reads a webpage, than it doesnt do it without a card to me to confirm. And then if sam has it setup that it needs his approval to text him, then it does that one. So 2 types of authority. You know." | review log, lines 259 to 262 |
| A card to oneself (§3) | "If my authority isnt enough to message Sam, then no card to myself is going to raise it above my authority." | review log, line 195; summary, line 11 |
| The tool list and the two cards (§4, §5) | §5's quotation | review log, lines 278 to 287; summary, line 12, elided there |

That the rule replaces ADR-0367 §4:6's floor for a message to a hub person is the review session's
reading (summary, line 11). **This decision's own, not ruled:** §1; §2:1's statement of the two
checks as the one check's outcomes; the first card's two grounds and one card for both (§2:2,
§2:3); whom the second card names (§2:4); §2:5's grounds and §2:6; §3's wording and §3:3's reach;
the ceiling at the sureness and the authority carried (§4:1), and §4:2 to §4:5's wording; §5's
reading in the corpus's terms; and §6 to §9.

## Consequences

- A call that falls short of its work's authority asks the person whose work it is, and one whose
  permission asks asks the person it names; nothing else asks for either.
- A work is shown what its person could do or ask for, so a falling score hides nothing.
- **Revisit** once the floor card on a disclosing call under a default alone is ruled (§9), or once
  a second person's cards are built.
- **Set aside:** a card to the sender wherever only a default grant allows a message (it asks no one
  who can supply anything); and hiding a tool whose permission only asks (the model could not ask).
