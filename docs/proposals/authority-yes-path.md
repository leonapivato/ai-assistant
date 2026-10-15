# Authority: your yes, for the deploy

**The question.** When authorizing says a call needs you, how does the assistant ask, how does your
answer become permission, and how is the call checked and run? What is the smallest version of this
the deploy can wait for, and what does it leave to later designs?

## The baseline

The wiki at [84f20c8](https://github.com/leonapivato/ai-assistant/wiki) holds the direction for this
milestone on [Authorizing](https://github.com/leonapivato/ai-assistant/wiki/Authorizing) (owner,
2026-09-27 and 2026-10-05). Related pages:
[Permission and approval](https://github.com/leonapivato/ai-assistant/wiki/Permission-and-approval),
[Confirmation](https://github.com/leonapivato/ai-assistant/wiki/Confirmation),
[Outside-content lineage](https://github.com/leonapivato/ai-assistant/wiki/Outside-content-lineage),
[Planning](https://github.com/leonapivato/ai-assistant/wiki/Planning) and
[Stories](https://github.com/leonapivato/ai-assistant/wiki/Stories).

**On `main` at `2ff6298c`** (PROTOCOL 105), the phases are the only path. ADR-0306 to ADR-0309 decided
them, ADR-0312 to ADR-0320 corrected and completed them, and the cutover deleted the old turn loop.
Nothing is deployed yet: the deploy waits for this milestone's acceptance run (ADR-0309 §6).

**How the build handles a call that needs you today:**
- **Authorizing checks every call by rule** (ADR-0306 §4): the policy, then the outside-content
  stand-in, then `MemoryPolicy` for remembering. The round's message is checked by its place.
- **"Confirm" means *needs you*.** The call runs nothing, parks nothing, and nothing resumes it
  (ADR-0306 §4:8).
- **Planning answers it** with "it cannot be done yet" (ADR-0307 §9:4). Planning's instructions add
  that nothing the user says can let it run (`_NEEDS_YOU`, #2853).
- **The old answer path is deleted:** parks, `resume`, goal authorizations and quotes, the deferred
  memory questions, the recipient grant's establishing act, and the confirmation surfaces (ADR-0313,
  ADR-0318 to ADR-0320). Where a retired clause's subject was authority, this milestone redoes it
  (ADR-0319 §3:4, ADR-0320 §7:4).

**What survives with no caller, kept for this milestone (#3048):**
- `ActionPolicy.resolve`;
- `PermissionDecision.authorises` and `from_confirmation`;
- `EgressBinder.rebind`;
- `UserConfirmation`, which `MemoryPolicy` still honours and which no lane may produce until this
  milestone decides how (ADR-0319 §6:1);
- the recipient-grant store with its listing and revoke (ADR-0313 §5:2);
- destination trust, whose act is live although nothing reads it.

Every ruling below is the owner's, from the walks of 2026-10-12 and 2026-10-15.

## 0. The frame

**Like a human assistant.** A human assistant has three sources of permission:
1. what the boss asked for, including a yes to something the assistant proposed;
2. a standing mandate;
3. nothing else.

**Where the assistant differs:** wherever a human relies on an instinct the AI lacks, the AI gets a
rule.

**Permission is not care.** Authority answers *am I allowed to do this?*. Whether the assistant got it
right is care, which is planning's judgment. Planning may always check with you before acting.

**Two stages.**
- **At the deploy,** you authorize an action that needs you by saying yes to a question that showed
  it.
- **Later,** a direct instruction or a standing delegation also authorizes. That stage rests on a
  separate design (§8).

## 1. Asking

1. **When a call comes back *needs you*,** planning decides whether to ask about it in its next round.
   A call it does not ask about is dropped. **Nothing is waiting on you that you were not clearly asked
   about, in a message you could see.**
2. **How it reads.** Planning explains the action in its own words, told to explain the arguments that
   matter. Code then appends **one exact line** listing every argument the call sends, except those the
   hub fills in itself, which are also left out of the comparison in §3:
   > I found a room at the Watchman for the 14th, $289 for one night, with free cancellation until the
   > 12th. Want me to book it?
   > *Exact request: book_stay · The Watchman (Springdale, UT) · 2026-11-14 · 1 night · 1 guest*

   - One generic renderer writes the line for every capability.
   - A test checks that it includes every argument the call sends.
   - Where a question carries several actions, each line is numbered, so "just the first" is easy to
     read.
3. **What is kept.** The round records the exact calls its question asks about, with their values and
   bindings. The decision trail keeps only a parameters digest, so the round must keep the values.
4. **What planning is told.**
   - **How approval works here,** in its standing instructions:
     - some actions need the user's yes;
     - when one does, ask, and the system shows the exact details;
     - the user's yes in reply lets that exact action run, once;
     - the assistant never approves on the user's behalf;
     - there is no other route: no confirmation emails, no steps "on their end".
   - **What happened to each call,** in that call's outcome:
     - *needs the user's yes: ask, and the details will be filled in*;
     - *not allowed by the user's settings: do not ask, say so*;
     - *needs the user, but this activation cannot message them: it will not run*.

   These replace `_NEEDS_YOU` and its outcome text, which today say the opposite.
5. **No buttons.** Questions are ordinary messages (ADR-0307 §3:6). Voice is retired until #2889.

## 2. The answer

1. **An answer is an activation like any other.** Understanding reads whether your input answers a
   question, which one, and which parts. It records a pointer: *your input answers the question in
   message E3, part 1*. The pointer is a reading and grants nothing by itself.
2. **Understanding sees the question as an ordinary message.**
   - In the place window, each item carries the label of the activation that wrote it (ADR-0303 §7:1).
   - An older question, or one asked in another conversation, comes back through recall and the story
     with its labels.
   - Nothing else is shown: there is no separate list of unanswered questions.
3. **Who can answer.** Only input that carries your authority (ADR-0292 §5): at the deploy, a message you
   sent through the hub chat. An email or an event that says "yes" approves nothing.
4. **Which question is understanding's judgment, inside the rules of §3.**
   - A reply to the question's message is a strong hint.
   - A bare "yes" that could fit more than one question gets "yes to which?", never a guess.
5. **What a reply can be:**
   - **yes** approves every part shown;
   - a **partial yes** approves only those parts;
   - **no** approves nothing, and a later "actually, yes" still works;
   - a **change** ("make it 8") approves nothing, and planning asks again with the new values;
   - an **unclear** reply approves nothing, and the assistant asks again;
   - a **conditional yes** counts as a change, because there are no timers to act later.
6. **A question does not expire,** and nothing opens or closes it. Whether it has been changed, has
   gone stale or was already dealt with is understanding's reading of the story.
7. **A mixed message** ("yes, and also email Bob") has its yes recorded, and the rest is handled as a
   normal request.

## 3. After a yes: how the call is checked and run

1. **Your yes's activation runs it.** Planning is shown each approved action under a label and proposes
   "do approved action 1". Code fills in the exact values from the record and reuses the original
   binding. The approval is used only by that activation.
2. **The policy, fresh.** A deny refuses, and neither your yes nor the spend ceiling (ADR-0194) is
   overridden. An allow runs. A confirm goes on to the three facts.
3. **Three facts, checked by rule against the records:**

   | Fact | Read from |
   | --- | --- |
   | **Shown to you:** the question's message reached one of your conversations | The message's delivery record (ADR-0306 §5) |
   | **Exactly the call shown:** the same tool, every value except the hub's own, and the same binding | The call against the call recorded with the question |
   | **Not already run:** that part of that question has not been used | The effect records |

4. **The approval** is assembled by code from these records, in a general shape that later kinds of
   approval extend:

   | Slot | At the deploy |
   | --- | --- |
   | **Who** | you, through the hub chat |
   | **How** | a yes to a question |
   | **Covers** | exactly the calls shown |
   | **Given** | in your yes message |
   | **Ends** | when used |

   It is recorded in the decision ("allowed by your yes at 2:15 to the question in that message,
   part 1"), and read back before anything runs (ADR-0037 §2–§3).
5. **Spending is keyed by the question's part.** Acting marks the part used in the same plan-store step
   that claims the call, so two yeses to one part cannot both run.
6. **A repeat is caught.** A proposed call identical to one still waiting on you gets "already asked,
   waiting on you", not a second question.
7. **A yes overrides every confirm,** the outside-content stand-in's included, because the values were
   shown. **It never overrides a deny.**
8. **If the world changed** (the slot is gone, the price differs), the call runs as approved, and a
   failure or a different charge is reported. Nothing is substituted.
9. **Every failure ends in another question.** Each piece of the approval has a writer, and if any
   piece is missing the check fails toward asking again, never toward running something you did not
   approve:
   - the recorded calls: code, when the round is saved;
   - delivery: code, when the message is sent;
   - the spend: code, in the claim, which no call can skip;
   - the pointer: understanding.

   A misread pointer can only land on another question you were shown.

## 4. Memory asks

1. **A remember that `MemoryPolicy` asks about needs you.** Planning asks with the exact statement.
2. **Your yes saves it as confirmed by you, and its source is kept on the record.** This is
   `UserConfirmation`'s producer, the one ADR-0319 §6:1 leaves to this milestone. It is your assent to
   text you were shown, not a model's paraphrase claiming your standing (ADR-0098 §4). How much weight a
   confirmed memory carries is the learning milestone's call.
3. **Other answers.**
   - **No:** it is not saved.
   - **A change:** a new question with the corrected statement.
   - **No answer:** the question stays answerable.
4. **A conflict found only at write time** (#2845) becomes *needs you*, not *not done*. The question
   shows both statements ("replacing …"), and a yes writes the new one and retires the old.
5. **What is asked about** stays the built `MemoryPolicy` until learning revisits it.
   - **Interim:** while the outside-content mark spreads (#2856), nearly every remember after a web
     search asks. Your yes saves it.
   - The fix belongs to the separate design (§8).

## 5. Retrying after an unknown outcome

A retry is an action like any other (#2839). A deliberate repeat that matches an effect whose outcome
is unknown, or not yet written, needs you instead of being refused. A yes to an ordinary question
showing the call lets it run. Mentioning the risk of a double is planning's care. Nothing is retried
without your yes.

## 6. What retires and what stays

- **Recipient grants retire fully:** the store, the listing and revoke commands, and the policy's
  recipient-grant route. ADR-0313 and ADR-0319 said this milestone "redoes the act". Instead the act is
  **replaced by scoped delegations** (§8). The deploy starts from a fresh data directory, so nothing is
  lost.
- **Destination trust retires fully:** the act, its commands and routes, the store and the code.
  - Its only reader, the old search composer, is gone.
  - Which destination may be told what comes back with the separate design (§8).
  - Web search is unaffected: the configured provider has its own setting (ADR-0247), which stays.
- **Whose input counts:** only input the channel establishes as yours, sent as an instruction. At the
  deploy, that means the hub chat.
- **Activations started by a timer or an event** cannot write a message (ADR-0307 §3). A call that
  needs you there does not run, and the text stays in the episode. This lasts until planning can write
  to a place other than the input's, when the same question path applies.
- **No new screen.** What is waiting on you is the questions in your conversations.
  `assistant decisions`'s "asked (a question put to you)" becomes true (#3056).
- **The deploy configures email sending,** so email is the live hub's first action in the world. Booking
  stays the simulator, on the test hub.

## 7. Acceptance before the deploy

*T* is the test hub; *L* is the live hub after the deploy.

1. **A booking (T).** It is asked, showing planning's explanation and the exact line. A yes runs it
   once, and a second yes does not run it again. Proposing it again while it waits gets "already
   asked".
2. **The other answers (T).**
   - "No" runs nothing, and a later "actually yes" works.
   - A change brings a new question.
   - An unclear reply runs nothing and asks again.
3. **Only you approve (T).** An email or event saying "yes" approves nothing.
4. **A yes from elsewhere (T).**
   - A yes in another conversation, or days later, works through recall and the story.
   - A bare "yes" with nothing to connect it to gets "yes to what?".
5. **Memory (T).** After a web search, "remember …" asks, and a yes saves it as confirmed by you, with
   its source kept.
6. **A retry (T)** after an unknown outcome runs only on a yes.
7. **A deny (T)** is never asked about, and planning says plainly that it is not allowed.
8. **#2862 (T).** The original scenario and variants, run 10 to 20 times each. No invented approval
   steps, and the booking runs once after the yes. These runs decide whether the held layer (§9) is
   needed.
9. **Email (L).** "Email Sam that I'm running late" shows the full text in the exact line, and a yes
   sends it once.
10. **The exact line (test suite)** includes every argument the call sends, for every capability.
11. **The retired commands are gone:** recipient grants and destination trust.

## 8. What a later design supplies, and the interim

The outside-content and provenance design is a separate walk
([#2856](https://github.com/leonapivato/ai-assistant/issues/2856) and its handoff). Its direction, not
ruled here:
- track **who contributed** to each value and fact, rather than marking whole activations;
- **compartments**: narrow model calls whose inputs code controls, so their outputs' sources are known;
- a **clean writer** for outgoing text;
- **scoped delegations**, with an instruction as a temporary one;
- outside content decides only within what you handed over, and only from the party you handed it to;
- **credibility** is for belief only, never authority.

This proposal relies on that design as follows:

| The deploy would want | Supplied later by | Interim at the deploy |
| --- | --- | --- |
| Saving what you say without asking, after a web search | Per-fact provenance (the quote check, then extraction) | `MemoryPolicy` asks, and your yes saves it |
| A confirmed memory keeping its source precisely | Source labels per fact | The outside-content mark plus the `UserConfirmation` record |
| Standing permission ("my brother may add family events") | Scoped delegations | None: every action in the world asks |
| Outgoing text that outside content cannot shape | The clean writer | Every send shows its full text and asks |
| One web search not marking every later activation | Retiring the activation-level mark | The mark stays, failing in the safe direction |
| A direct instruction approving without a question | The instruction path, built on the above | Every action the policy confirms asks once |

Nothing in the deploy slice reads the activation-level mark. The approval's general shape (§3:4) is
what later kinds of approval extend.

## 9. Held

**Code-written sentences for the cases with no route:** "your settings don't allow this", and "this
needs you, but I can't ask from here". They are held until the repeated runs (§7:8) show planning's own
wording is not enough.

## 10. Changes to ratified decisions

| Decision | Change |
| --- | --- |
| ADR-0306 §4:8 | *Needs you* gets an answer: a yes to a question that showed the call. "Nothing resumes it" stands, because the answer is a new activation. |
| ADR-0306 §4:3 | Memory that `MemoryPolicy` asks about is written on your yes, as confirmed by you, with its source kept. |
| ADR-0306 §5:11, §5:13 | A deliberate repeat matching an unknown or unwritten effect needs you, instead of never passing. "Never retried" applies to the assistant's own initiative. |
| ADR-0307 §2, ADR-0315 §3:1 | The round's record also keeps the exact calls its question asks about. |
| ADR-0307 §3:6 | Stands: an answer names no question. Understanding infers which question it answers, and records that as its pointer. |
| ADR-0307 §9:4 | A call that needs you is asked about, not answered "cannot be done yet". Planning is told how approval works, and each call's outcome says which case applies. |
| ADR-0276 | Understanding's record gains the answer pointer. The record still grants nothing by itself. |
| ADR-0192 | An approval from a yes is spent per question part, marked in the claim. |
| ADR-0148 §8 (§8:4 already superseded by ADR-0319) | What a question shows is re-enacted: planning's explanation plus the exact line of every argument. |
| ADR-0154 §4:1 (Condition 12, per ADR-0320 §8) | The decision names the approval, and the effect record carries the claim and the outcome. Together they keep the attempt identifier and the explicit outcome. |
| ADR-0313 §5:2, and the ADR-0193 and ADR-0235 rows of ADR-0313 §8 and ADR-0319 §8 | Recipient grants retire. The establishing act is replaced by scoped delegations, not redone. |
| ADR-0238, ADR-0242 | Destination trust retires. |
| ADR-0319 §6:1 | The memory yes is `UserConfirmation`'s producer. |

## Options considered

- **Code renders the whole question.** Rejected for the deploy: planning explains better. The exact
  line keeps the guarantee that what you see is what runs.
- **The model writes the question with no exact line.** Rejected: a mistake or a steered description
  would get your yes for something other than what runs.
- **Showing every value in custom displays, with tiers.** Rejected as over-built for now.
- **Code guaranteeing that every needs-you call is asked about.** Rejected: the QA failures came from
  an instruction saying no route existed. Asking is planning's call, and an unasked call is dropped.
- **A list of unanswered questions shown to understanding and planning.** Rejected: the window, recall
  and the story already show them, and messages link to their activations.
- **Questions that open and close, or expire after a day.** Rejected: spending covers reuse, and
  staleness is a reading of the story.
- **A stored approvals table at the deploy.** Not needed: an approval is used only by its yes's
  activation. Stored approvals come with delegations.
- **Reading money back, or a stakes dial.** Rejected: money is not an exception, and double-checking is
  care, not permission.
- **A model judging whether "Sam" matches an address.** Rejected for authority: it is not a rule.
- **Recipient grants redone now.** Rejected: delegations replace them.

## What it leaves open

- **The outside-content and provenance design** (§8), with #2856, #2798, #2846, #2847 and #2590.
- **A price that comes back as a result** is not checked against what was shown. At the deploy only the
  simulated booking charges, so reporting it afterwards is enough. A real paid capability needs the
  shown price to bind the call: a maximum argument, or a fresh quote checked before acting (the shape
  ADR-0267 used).
- **The recheck after the lock** belongs to the concurrency milestone (#2586).
- **Unattended limits** (#2583) and volume caps arrive with timers.
- **Other channels and voice identity** (#2819, #2582, #113).
- **The numbers** (#2589) for the phases. The yes path itself needs none.
- **Crash recovery of a claimed call** (#2584).

## Delivery, roughly

One ADR converts this proposal. Its number is the next free one, 0321 or higher, taken after a scan at
conversion. The lanes after it are a sketch:

1. **Types:**
   - the round's asked calls;
   - understanding's answer pointer;
   - the approval's general shape;
   - the label kind for approved actions;
   - the part key on the effect record;
   - a `PROTOCOL_VERSION` bump.
2. **Authorizing:**
   - the three facts;
   - assembling and recording the approval;
   - the repeat check;
   - the backstop change.
3. **Acting:** spending per part, in the claim.
4. **Planning:**
   - asking;
   - the exact line;
   - how approval works;
   - the per-call outcome notes;
   - approved actions by label.
5. **Understanding:** reading answers into the pointer.
6. **Memory:** the yes as `UserConfirmation`'s producer, and #2845.
7. **The retirements:** recipient grants, and destination trust.
8. **The acceptance runs** (§7).
