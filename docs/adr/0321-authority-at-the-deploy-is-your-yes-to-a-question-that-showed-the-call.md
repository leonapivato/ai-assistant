# 321. Authority at the deploy is your yes to a question that showed the call

- Status: Partially superseded by ADR-0322 (§3:1's one pointer: one per question; §3:2, in the addition alone: questions are marked and labelled; §3:6, per question; §9's `ProposedActivationUnderstanding` and `ActivationUnderstanding` rows: the pointer becomes a sequence) and ADR-0323 (§3:3's second sentence, §4:4's *in one of your conversations* and §4:6's *through the hub chat*, each restated without naming a channel) and ADR-0328 (§5:3) and ADR-0329 (§4:4's and §4:17's `MemoryPolicy` limbs, replaced by *confirm*; §5:1, §5:2, §5:5, §5:6 and §5:7) and ADR-0338 (§2:5 and §2:7, in the additions alone: a `pin` or `unpin` call's exact line shows the memory's wording; §4:4 and §4:17, in the additions alone: `set_profile`, `pin` and `unpin` as a source of *needs you*) and ADR-0353 (§3:1's pointer and §3:4–§3:11's readings of an answer, until a later decision: understanding records no pointer) and ADR-0356 (§2:3, in the response's carrying of the naming alone: `RoundResponse` carries none) and ADR-0357 (§2:3, in where the calls are named alone: the `asks` argument of the round's asking `text` call; §2:4's and §2:9's instruction lines, in where they are said alone: that argument's description; §2:5's *the message*: the asking `text` call's words, after any rewording; §2:8's *its message*: the round's one asking message) and ADR-0361 (its asking path, in the clauses ADR-0361 §11 names: a person approves by tapping a card, and a yes grants a one-time ticket)
- Date: 2026-10-15
- Scope: the authority milestone, M44 ([milestone #11](https://github.com/leonapivato/ai-assistant/milestone/11)), acceptance [#3058](https://github.com/leonapivato/ai-assistant/issues/3058), batch [#3059](https://github.com/leonapivato/ai-assistant/issues/3059): how the assistant asks about a call that needs you, how your answer becomes permission, and how the call is then checked and run. It is the smallest version the deploy waits for (ADR-0309 §6).
- Dependency: the phases as ADR-0306 to ADR-0309 and ADR-0312 to ADR-0320 decide them, all Accepted and built on `main` at `2ff6298c`.
- Authorization: the owner accepted proposal [#2850](https://github.com/leonapivato/ai-assistant/pull/2850) on 2026-10-15, at `02a910a6`, and the dispatcher assigned 0321. Every ruling below is the owner's, from the walks of 2026-10-12 and 2026-10-15. This ADR is that proposal converted under `docs/proposals/README.md` → "When it is decided".
- **Changes `core`, so it is a contract-surface decision.** `RoundResponse` and `PlanningRound` gain the asked calls; `ProposedActivationUnderstanding` and `ActivationUnderstanding` gain the answer pointer; `PermissionDecision` gains the approval; `ActivationEffect`, `ActivationEffectClaim` and `PlanStore.claim_activation_effect` gain the approval's spending; `LabelKind` gains a member; `UserConfirmation` names the question it answers; and the recipient-grant and destination-trust types, Protocols, errors and engine members leave. Several cross the wire, so `PROTOCOL_VERSION` advances (§9).
- **Supersedes**, each whole (§10):
  [ADR-0235](0235-the-establishing-act-rides-an-answer-to-a-confirmation-live-or-recorded-and-a-refused-search-reaches-the-user-as-history-and-not-as-work.md) and
  [ADR-0242](0242-the-act-that-trusts-a-destination-has-its-own-surface-and-a-search-that-did-not-happen-is-explained-in-the-reply.md).
- **Partially supersedes**, each in the scope §10 states:
  [ADR-0152](0152-the-binding-is-derived-at-one-seam-never-supplied-to-it-and-a-call-it-cannot-describe-is-refused.md),
  [ADR-0192](0192-an-authorisation-is-spent-by-the-act-it-authorises-and-the-trail-gains-an-invocation-row.md),
  [ADR-0193](0193-a-standing-recipient-grant-is-a-user-act-on-a-canonical-destination-set-and-never-covers-a-call-planned-over-external-content.md),
  [ADR-0236](0236-the-operator-declares-what-one-web-search-costs-and-where-none-is-declared-the-search-confirms-on-that-ground-as-well.md),
  [ADR-0238](0238-a-destination-the-user-chose-may-be-told-what-the-turn-knows-and-the-searching-that-follows-runs-under-a-per-conversation-budget.md),
  [ADR-0247](0247-the-configured-web-search-provider-is-the-destination-the-owner-chose-and-the-recipient-they-granted-and-the-call-budget-is-removed.md),
  [ADR-0260](0260-a-forecast-read-is-its-own-seam-at-a-configured-provider-and-what-it-mints-carries-the-extent-that-makes-it-evidence.md),
  [ADR-0272](0272-the-trail-admits-a-digest-free-standing-row-on-the-kinds-own-configured-provider-fact.md),
  [ADR-0276](0276-an-activation-is-understood-before-it-is-associated-and-the-understanding-is-retained-with-its-episode.md),
  [ADR-0306](0306-a-capability-declares-what-its-calls-do-every-call-is-checked-by-rule-and-acting-claims-and-records-what-it-does.md),
  [ADR-0307](0307-a-planning-round-is-one-model-response-that-writes-its-own-message-keeps-episode-notes-and-names-what-it-was-shown-by-label.md),
  [ADR-0313](0313-spoken-conversation-retires-at-the-cutover-an-event-returns-how-it-ended-and-the-establishing-act-leaves-the-engine.md),
  [ADR-0315](0315-a-round-that-made-a-call-brings-another-round-and-the-mark-asking-for-one-retires.md) and
  [ADR-0319](0319-the-decisions-the-cutover-left-standing-over-deleted-code-retire-the-stamp-drops-recalls-limit-and-an-unasked-memory-question-is-logged.md).
- Partially superseded: 2026-10-15 by ADR-0322 — four narrow scopes. §3:1's one pointer becomes one per question the input approves, naming it by the question's own label, and a reply approves several only where it says which (ADR-0322 §2:1–§2:2, §4:5). §3:2 gains, in the addition alone, a mark and a label on each message that is a question; *nothing lists unanswered questions* stands (ADR-0322 §4). §3:6 applies per question (ADR-0322 §2:4). §9's `ProposedActivationUnderstanding` and `ActivationUnderstanding` rows carry a sequence of pointers (ADR-0322 §6). §3:5, §3:10 and §4 stand, applied to each question separately (ADR-0322 §3). These replacements take effect on ratification of ADR-0322. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; the ratified body below is preserved.
- Partially superseded: 2026-10-17 by ADR-0323 — three narrow scopes, each restated without
  naming a channel. §3:3's second sentence: input approves only where its author is one its
  channel's kind establishes as the user and it was sent as an instruction; an email, an
  event or a forward saying yes approves nothing (ADR-0323 §4:7). §4:4's *in one of your
  conversations*: in a place whose kind establishes the user as an author there, the
  Telegram line's chat among them (§4:8). §4:6's *who*'s *through the hub chat*: through the
  channel the yes came on (§4:9). §3:3's first sentence, §4:4's three facts, §4:6's other
  four slots and every other clause stand. This replacement takes effect on ratification of
  ADR-0323. This reciprocal header record accompanies the numbered draft under ADR-0070 and
  ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-18 by ADR-0328 — §5:3: a confirmed memory carries a confirmation support and stands at "you confirmed this wording" (ADR-0328 §13). This replacement takes effect on ratification of ADR-0328. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-18 by ADR-0329 — §4:4's and §4:17's `MemoryPolicy` limbs, replaced by `remember`'s *confirm* argument as a source of *needs you* (ADR-0329 §5:2–§5:3). §5:1, §5:2, §5:5, §5:6 and §5:7: no `remember` call passes `MemoryPolicy`; a yes to a *confirm* records the candidate under the approval, from which the observer adds a confirmation support; and `MemoryPolicy`'s asks on the observer's writes become open questions (ADR-0329 §5, §12, §13). §5:4 and every other clause stand. This replacement takes effect on ratification of ADR-0329. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-21 by ADR-0338 — §2:5 and §2:7, in the additions alone: a `pin` or `unpin` call's exact line shows the memory's wording as stored in place of its label, and the exact line's test reads that wording as the argument the call sends (ADR-0338 §8:6). §4:4 and §4:17, in the additions alone: `set_profile`, `pin` and `unpin` need you by rule, beside the policy's confirm, the stand-in's and `remember`'s *confirm*, with the policy's recorded allow as the deciding decision (ADR-0338 §8:5). Every other clause stands. This replacement takes effect on ratification of ADR-0338. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-27 by ADR-0353 — §3:1's pointer, and §3:4–§3:11's readings of an answer, until a later decision redesigns approvals: understanding is shown no question mark, its reply carries no answer, and it records no pointer, so §4 finds none and no yes approves anything (ADR-0353 §11). Every other clause stands. This replacement takes effect on ratification of ADR-0353. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-30 by ADR-0356 — §2:3, in the response's carrying of the naming alone: `RoundResponse` carries no `asks`, and no implementation carries a naming in the provider's native shape (ADR-0356 §7:5). Where the calls are named is the tools decision's, which records it here itself. Every other clause stands. This replacement takes effect on ratification of ADR-0356. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-30 by ADR-0357 — four scopes. §2:3, in where the calls are named alone, ADR-0356 having taken the response's carrying of the naming: the calls a question asks about are named in the `asks` argument of the round's asking `text` call (ADR-0357 §8:1). §2:4's *its instruction tells it* and §2:9's *Planning's standing instructions say*, each in where it is said alone: the description of `text`'s `asks` argument says it (ADR-0357 §7:2). §2:5's *Code appends to the message*: to the asking `text` call's words, after any rewording (ADR-0357 §8:2). §2:8's *its message*: the round's one asking message (ADR-0357 §8:3, §8:4). Every other clause stands as its other records leave it, §2:6 and §4 included. This replacement takes effect on ratification of ADR-0357. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-31 by [ADR-0361](0361-approvals-are-cards-the-person-taps-and-a-yes-is-a-one-time-ticket-for-the-exact-call.md) — its asking path. §2:2's *in a message you could see*: on a card. §2:3, §2:6, §2:8 and §2:12, whole. §2:4's and §2:9's instruction lines: `request_approval`'s description says them. §2:5's *appends to the message*: the card shows the exact line. §2:10's first case: a direct call needing a yes is to be called through `request_approval`; its third case, whole. §3, whole: no input approves anything. §4:1: only the work holding the approval's input uses its ticket. §4:4–§4:5: `run_approved`'s checks against the store. §4:6, in the addition alone: a tap's form. §4:9's key: the request. §4:12: a pending request for the same call. §4:14's pointer and delivery. §5:1's *asks about it*: by `request_approval`. §5:4's *stays answerable*: until it expires, 24 hours after it is written. §7:3 and §7:4, whole. §9:1's rows for the question path (ADR-0361 §2, §4, §5, §8). Every other clause stands. This replacement takes effect on ratification of ADR-0361. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.

## Context

**The question.** When authorizing says a call needs you, how does the assistant ask, how does
your answer become permission, and how is the call checked and run? The wiki's
[Authorizing](https://github.com/leonapivato/ai-assistant/wiki/Authorizing) page at `84f20c8`
holds the direction (owner, 2026-09-27 and 2026-10-05).

**Where `main` stands at `2ff6298c`.** The phases are the only path, and nothing is deployed.
- Authorizing checks every call by rule: the policy, then the outside-content stand-in, then
  `MemoryPolicy` for remembering (ADR-0306 §4:1–§4:3).
- *Confirm* means *needs you*: the call runs nothing, parks nothing, and nothing resumes it
  (ADR-0306 §4:8). Planning answers it with "it cannot be done yet" (ADR-0307 §9:4), and
  `_NEEDS_YOU` in `orchestration/planning.py` adds that nothing the user says can let it run.
- The old answer path is deleted: parks, `resume`, goal authorizations and quotes, the deferred
  memory questions, the recipient grant's establishing act, and the confirmation surfaces
  (ADR-0313, ADR-0318 to ADR-0320).
- Kept with no caller for this milestone
  ([#3048](https://github.com/leonapivato/ai-assistant/issues/3048)): `ActionPolicy.resolve`,
  `PermissionDecision.authorises` and `from_confirmation`, `EgressBinder.rebind`,
  `UserConfirmation` (no lane may produce one until this milestone decides how, ADR-0319 §6:1),
  the recipient-grant store with its listing and revoke (ADR-0313 §5:2), and destination trust,
  whose act is live although nothing reads it.

**Why now.** [#2862](https://github.com/leonapivato/ai-assistant/issues/2862) showed the cost of
an instruction that says no route exists: planning invented approval steps ("it comes back
needing your authorization through the booking system itself — that's a step that happens on
your side"), and a user's yes made it propose the call again, which needed them again.

**The frame.** A human assistant acts on what the boss asked for, a yes to something the
assistant proposed included, or on a standing mandate, and on nothing else. Where a human relies
on an instinct the AI lacks, the AI gets a rule. Permission is not care: authority answers *am I
allowed to do this?*, and whether the assistant got it right is planning's judgment, which may
always check with you first. Authority comes in two stages. At the deploy, you authorize an action
that needs you by saying yes to a question that showed it. Later, a direct instruction or a
standing delegation also authorizes, on a separate design.

**What the yes path rests on.** The facts that can be checked are checked by rule: the question
was shown to you, the call is exactly the one shown, and it has not already run. The readings
belong to understanding and the story: which question an input answers, and whether a question
has gone stale. A misread can only land on another question you were shown, so every failure
ends in another question rather than in running something you did not approve.

## Decision

We will let an action that needs you run on your yes to a question that showed it, in the
yes's own activation, after the policy is asked fresh and three facts are checked by rule.

### 1. Status and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the owner's acceptance
> and the dispatcher's authorization to ratify stand.

> **Normative.** No lane implements this decision until it has merged `Accepted`. Its lanes
> are cut then, under batch #3059.

### 2. Asking

> **Normative.** When a call comes back needing you, planning decides whether its next round
> asks about it.

> **Normative.** A call that no round's message asks about is dropped: nothing waits on you
> that you were not clearly asked about, in a message you could see.

> **Normative.** A round names, in its response, the calls that came back needing you that its
> message asks about. The naming is a part of the response and never a call, and how the
> provider's native shape carries it is the `models/` implementation's, as for the notes
> (ADR-0315 §3:3).

> **Normative.** Planning explains each action it asks about in its own words, and its
> instruction tells it to explain the arguments that matter.

> **Normative.** Code appends to the message, for each call it asks about, one exact line
> listing every argument the call sends, written by one generic renderer for every
> capability. The arguments the hub fills in itself are left out: those a declaration names
> in `system_supplied`, the *looking for* argument and the *deliberate repeat* mark
> (ADR-0306 §2:9–§2:10).

> **Normative.** Where a message asks about several calls, each exact line is numbered, and
> its number is that call's part of the question.

> **Normative.** A test checks, for every capability, that the exact line includes every
> argument the call sends except those §2:5 leaves out.

> **Normative.** The round records each call its message asks about, with its part, the tool
> selection picked, the values it sends, its binding, and whether planning marked it a
> deliberate repeat. The decision trail keeps only a parameters digest, so the round keeps
> the values.

> **Normative.** Planning's standing instructions say how approval works here: some actions
> need the user's yes; when one does, planning asks, and the system shows the exact details;
> the user's yes in reply lets that exact action run, once; the assistant never approves on the
> user's behalf; and there is no other route, no confirmation emails and no steps on the
> user's end.

> **Normative.** Each call's outcome tells planning which case applies: it needs the user's
> yes, so ask, and the details will be filled in; the user's settings do not allow it, so do
> not ask, and say so; or it needs the user and this activation cannot message them, so it
> will not run. These replace `_NEEDS_YOU` and the needs-you outcome text.

> **Normative.** Planning's standing instructions carry one line of care: check with the user
> first when unsure what they meant, or when a mistake would be costly, even where their
> authority already covers the action. It grants and withholds nothing.

> **Normative.** A question carries no buttons and no options. It is an ordinary message
> (ADR-0307 §3:6).

### 3. The answer

> **Normative.** An answer is an activation like any other. Understanding reads whether its
> input approves an earlier question, and records in its understanding a pointer naming that
> question's message and the parts the input approves. The pointer is a reading and grants
> nothing by itself (ADR-0276 §7:7).

> **Normative.** Understanding sees a question as the ordinary message it is: in the place
> window, labelled with the activation that wrote it (ADR-0303 §7:1), and, for an older
> question or one asked in another conversation, through recall and the story. Nothing lists
> unanswered questions.

> **Normative.** Only input that carries the user's authority (ADR-0292 §5:5) approves. At the
> deploy that is a message the user sent through the hub chat; an email or an event saying
> yes approves nothing.

> **Normative.** Which question an input answers is understanding's judgment, within §4's
> rules, and a reply to the question's message is a strong hint.

> **Normative.** A bare yes that could fit more than one question records no pointer and gets
> "yes to which?", never a guess.

> **Normative.** A yes approves every part shown, and a partial yes approves only the parts it
> names.

> **Normative.** A no approves nothing, and a later yes to the same question still approves.

> **Normative.** A change, such as "make it 8", approves nothing, and planning asks again with
> the new values. A conditional yes counts as a change, because nothing acts later on a timer.

> **Normative.** An unclear reply approves nothing, and the assistant asks again.

> **Normative.** A question does not expire, and nothing opens or closes it. Whether it was
> changed, has gone stale or was already dealt with is understanding's reading of the story.

> **Normative.** A message that mixes a yes with a request has its yes recorded, and the rest
> is handled as a normal request.

### 4. After a yes

> **Normative.** The yes's activation runs the calls it approved, and no other activation uses
> that approval.

> **Normative.** Planning is shown each approved action under a label of a new kind and
> proposes it by that label. Code fills in the values recorded with the question and reuses
> the recorded binding through `EgressBinder.rebind`, and nothing planning sends beside the
> label changes them.

> **Normative.** The approved call is checked fresh, as every call is (ADR-0306 §4:1). A deny
> refuses it, and neither your yes nor the spend ceiling (ADR-0194) is overridden. An allow
> runs it.

> **Normative.** Where the fresh checks rule that the call needs you, by the policy's confirm,
> the stand-in's or `MemoryPolicy`'s ask, authorizing checks three facts by rule against the
> records: **shown to you**, the question's message has a done delivery record in one of your
> conversations (ADR-0306 §5:5); **exactly the call shown**, the same tool, every value but
> those §2:5 leaves out, and the same binding as the call recorded with the question; and
> **not already run**, no effect record carries that part's key (§4:9).

> **Normative.** Where any fact fails, or understanding recorded no pointer, the call does not
> run under an approval and goes back to planning as needing you. Every failure ends in
> another question, never in running something you did not approve.

> **Normative.** Where the three facts hold, code assembles the approval from those records in
> one general shape: **who**, the user through the hub chat; **how**, a yes to a question;
> **covers**, exactly the calls of the approved parts; **given**, in the yes's input; and
> **ends**, when used. A later kind of approval extends this shape rather than replacing it.

> **Normative.** A confirm the policy rules, its lineage rule's (ADR-0181 §5) included, is
> resolved on route (a): the confirm ruled fresh in the yes's activation is recorded,
> `ActionPolicy.resolve` is asked with `approved=True`, and the resolving decision records
> `resolves` naming that confirm.

> **Normative.** Every decision about a call that runs under an approval names the approval,
> as "allowed by your yes at 2:15 to the question in that message, part 1" does, and is
> recorded and read back before anything runs (ADR-0037 §2–§3).

> **Normative.** Spending is keyed by the question's part: the asking round's id and the part
> number. A call that runs under an approval is claimed with that key in the plan-store step
> that claims it (ADR-0306 §5:4), and that step refuses it, writing nothing, where a record
> already carries the key, so two yeses to one part cannot both run.

> **Normative.** Every call that runs under an approval gets an effect record, whatever its
> capability.

> **Normative.** A yes overrides every confirm, the outside-content stand-in's included,
> because the values were shown. It never overrides a deny.

> **Normative.** A proposed call identical to one still waiting on you, the same tool, values
> and binding as a call asked about in this activation or in the episodes of its stories whose
> part no effect record has used, goes back to planning as already asked and waiting on you,
> and is not asked about again.

> **Normative.** If the world changed, such as the slot being gone or the price differing,
> the call runs as approved, and a failure or a different charge is reported. Anything else
> becomes a new question, and nothing is substituted.

> **Normative.** Each piece of the approval has one writer: the recorded calls, code when the
> round is recorded; delivery, code when the message is sent; the spend, code in the claim,
> which no call skips; and the pointer, understanding.

> **Normative.** For a call that runs under an approval, the deciding decision names the
> approval and the effect record, and the effect record carries the claim and the outcome.
> Together they are the attempt identifier and the explicit outcome ADR-0154 §4:1's
> Condition 12 requires.

> **Normative.** `EgressBinder.rebind` takes `forecast_reach` from the approved binding, as it
> takes `closed_loop`, so an approved forecast read rebinds equal to the binding that was
> shown. This is the fifth transcription ADR-0260 §11:7 leaves to the decision that rebinds a
> forecast binding.

> **Normative.** Where the policy allows and what needs you is the stand-in, which is
> orchestration's rule (ADR-0306 §4:4), or `MemoryPolicy`'s ask, the policy's recorded allow
> is the deciding decision. The approval lifts the stand-in, or reaches `MemoryPolicy` as
> §5:2 states, and no confirm is made outside `permissions`.

### 5. Memory asks

> **Normative.** A remember that `MemoryPolicy` rules to ask about needs you, and planning asks
> about it with the exact statement.

> **Normative.** Your yes saves it. Code builds a `UserConfirmation` from the approval and the
> remember carries it to `MemoryPolicy`, which honours it as ADR-0106 §6:1–§6:3 and ADR-0214
> §3:2 decide. This is `UserConfirmation`'s producer: your assent to text you were shown, not
> a model's paraphrase claiming your standing (ADR-0098 §4).

> **Normative.** A confirmed memory keeps its source: the provenance the proposal carries is
> written unchanged, and the remember's decision names the approval (§4:8). How much weight a
> confirmed memory carries is the learning milestone's.

> **Normative.** A no saves nothing; a change brings a new question with the corrected
> statement; and a question with no answer stays answerable.

> **Normative.** A conflict found only at write time
> ([#2845](https://github.com/leonapivato/ai-assistant/issues/2845)) comes back needing you,
> not not done. The question shows both statements, as "replacing …", and a yes writes the new
> one and retires the old as the memory writer supersedes. An assertion the question did not
> show is not retired on that yes: `MemoryPolicy` asks again, as it honours a
> `UserConfirmation` today.

> **Normative.** What is asked about stays the built `MemoryPolicy` until the learning
> milestone revisits it.

> **Normative.** Memory that `MemoryPolicy` rules to ask about during consolidation is still
> not written, and ADR-0319 §5 governs it.

### 6. A retry after an unknown outcome

> **Normative.** A deliberate repeat that matches an effect whose outcome is unknown or not yet
> written needs you, instead of being refused. Authorizing rules it so, reading the effect
> records the claim would match (ADR-0306 §5:9–§5:10).

> **Normative.** The claim of a deliberate repeat that runs under an approval passes a matching
> effect whose outcome is unknown or not yet written. Every other claim matches as ADR-0306
> §5:9–§5:11 decide.

> **Normative.** Nothing is retried without your yes. An unknown outcome is never retried, done
> another way or reported as done on the assistant's own initiative.

### 7. What retires and what stays

> **Normative.** Recipient grants retire fully: the store, the `recipient-grants`,
> `recipient-grant-log` and `revoke-recipient-grant` commands with their routes and engine
> members, and the policy's recipient-grant route, with every type and member only they use.
> Their establishing act is not redone: scoped delegations replace it, on a later design.

> **Normative.** Destination trust retires fully: the act, the `trust-destinations`,
> `destination-trust` and `revoke-destination-trust` commands with their routes and engine
> members, the store and its code. Which destination may be told what comes back with a later
> design. The configured search provider's setting (ADR-0247) and the forecast provider's
> (ADR-0260) stay.

> **Normative.** In an activation started by a timer or an event, which writes no message
> (ADR-0307 §3:8), a call that needs you does not run, and the text stays in the episode. This
> holds until planning can write to a place other than the input's, when the same question
> path applies.

> **Normative.** No lane builds a screen or listing of what waits on you: it is the questions
> in your conversations. `assistant decisions`'s "asked (a question put to you)" becomes true
> ([#3056](https://github.com/leonapivato/ai-assistant/issues/3056)).

> **Normative.** The deploy configures email sending: the owner sets `send_email_connection`
> and its endpoint as a deploy checklist step, so email is the live hub's first action in the
> world.

> **Normative.** Booking stays the simulator, on the test hub.

> **Normative.** `PermissionRuling.authorised_subject` stays, and nothing sets it. With no grant
> left to read, `AuditTrail.record` refuses a non-resolving `ALLOW` that carries one, and the
> configured-provider routes (ADR-0247 §2, ADR-0272) are told apart by its absence as before.

> **Normative.** The lane that retires recipient grants writes a dated note on ADR-0154
> recording that its §4's condition 3 holds by the first limb of ADR-0017 §3's disjunct alone
> again, the re-attestation ADR-0154 §4:1 asks of a change to it.

### 8. Acceptance before the deploy

Acceptance #3058 holds these checks; *T* is the test hub and *L* the live hub after the deploy.

> **Normative.** A booking (T) is asked, showing planning's explanation and the exact line; a
> yes runs it once, a second yes does not run it again, and proposing it again while it waits
> gets "already asked".

> **Normative.** The other answers (T): a no runs nothing and a later "actually yes" works; a
> change brings a new question; and an unclear reply runs nothing and asks again.

> **Normative.** Only you approve (T): an email or an event saying yes approves nothing.

> **Normative.** A yes from elsewhere (T): a yes in another conversation, or days later, works
> through recall and the story, and a bare yes with nothing to connect it to gets "yes to
> what?".

> **Normative.** Memory (T): after a web search, "remember …" asks, and a yes saves it as
> confirmed by you, with its source kept.

> **Normative.** A retry (T) after an unknown outcome runs only on a yes.

> **Normative.** A deny (T) is never asked about, and planning says plainly that it is not
> allowed.

> **Normative.** #2862's scenario and its variants (T) are each run 10 to 20 times, with no
> invented approval step, and the booking runs once after the yes. These runs decide whether
> the held code-written sentences are needed, and #2862 closes when they pass.

> **Normative.** Email (L): "Email Sam that I'm running late" shows the full text in the exact
> line, and a yes sends it once.

> **Normative.** The exact line's test (§2:7) passes for every capability.

> **Normative.** The recipient-grant and destination-trust commands are gone.

### 9. The code it binds

| Code | Change |
| --- | --- |
| `RoundResponse` | Gains the calls its message asks about, named as §2:3 states |
| `PlanningRound` | Gains the asked calls, a new type: each with its part, tool, values sent, binding and deliberate-repeat mark (§2:8) |
| `ProposedActivationUnderstanding` | Gains the proposed answer pointer, naming the question as understanding was shown it and the parts approved |
| `ActivationUnderstanding` | Gains the recorded answer pointer, the question's message resolved to its ids, with no label (ADR-0276 §2:4) |
| `LabelKind` | Gains the approved-action member, with its prefix |
| Approval | A new type with §4:6's five slots |
| `PermissionDecision` | Gains the approval, `None` on a decision about a call that does not run under one; `from_request` gains it as a recorder-supplied argument, as `effect` is |
| `PermissionDecision.from_confirmation` | Retires: the yes path resolves a confirm it holds the request for, so `from_request` builds the resolving decision |
| `ActivationEffect` | Gains the part key, set on a call that runs under an approval |
| `ActivationEffectClaim` and `PlanStore.claim_activation_effect` | The claim takes the part key and answers, writing nothing, where a record carries it (§4:9); and admits §6:2's retry |
| `UserConfirmation` | `deferral_id` gives way to the question it answers, its message and part; `question_key`, `confirmed_at` and `retires` stay |
| `_NEEDS_YOU` and the needs-you outcome text in `orchestration/planning.py` | Replaced by §2:9–§2:10 |
| `ActionPolicy.resolve`, `PermissionDecision.authorises`, `AuditTrail.record`'s resolution checks | Unchanged, and used by the yes path |
| `EgressBinder.rebind` | Used by the yes path, and takes `forecast_reach` from the approved binding (§4:16) |
| `RecipientGrant`, `RecipientGrants`, `RecipientGrantResolution`, `RecipientGrantStore`, their errors, `permissions/recipient_grants.py`, `orchestration/recipient_grants.py`, and the engine members, routes and commands named in §7:1 | Leave |
| `PermissionRuling.authorised_subject` and `AuditTrail.record` | The field stays, set by nothing; the trail refuses a non-resolving `ALLOW` carrying it (§7:7) |
| `DestinationTrust`, `DestinationTrustRecord`, `DestinationTrustStore`, their errors, `permissions/destination_trust.py`, `orchestration/destination_trust.py`, and the engine members, routes and commands named in §7:2 | Leave |

> **Normative.** The `core` types, `PlanStore` member and Protocols the table names change, are
> added or leave as it states. Each change lands as a Protocol triad, with its conformance
> suite and canonical fake, in the lane that builds it; exact field names and shapes are that
> lane's, within the table.

> **Normative.** Each change to a shape the wire carries advances `PROTOCOL_VERSION` on
> ADR-0124 §9's rule, and the deploy starts from a fresh data directory, so nothing stored
> before these fields is read.

### 10. Relationship to earlier decisions

| Earlier decision | What changes |
| --- | --- |
| ADR-0306 §4:3 | *Not written by planning until the authority milestone*: a remember it asks about is written on your yes (§5:2). Consolidation's limb stands (§5:7) |
| ADR-0306 §4:8 | In the addition alone: *needs you* is answered by a yes to a question that showed the call (§4). *Nothing resumes it* stands, because the answer is a new activation |
| ADR-0306 §4:12 | *The authority milestone redoes them*: the establishing act is replaced by scoped delegations and not redone (§7:1); quotes, stated bounds and charges are not redone here |
| ADR-0306 §5:3 | In the addition alone: every call that runs under an approval gets an effect record (§4:10) |
| ADR-0306 §5:9, §5:11, §5:13 | A deliberate repeat matching an unknown or unwritten effect needs you rather than being refused, and its claim passes under an approval (§6:1–§6:2); *never retried* is the assistant's own initiative (§6:3) |
| ADR-0306 §6:1, §6:2 | The `ActivationEffect` and `ActivationEffectClaim` rows and the claim's steps, in the additions alone: the part key and its refusal (§4:9), and §6:2's admission |
| ADR-0307 §5:1 | In the addition alone: the approved-action label (§4:2) |
| ADR-0307 §6:1 | In the addition alone: planning is given the approved actions of its activation (§4:2) |
| ADR-0307 §9:4 | Whole: a call that needs you is asked about, not answered "cannot be done yet" (§2:1, §2:10) |
| ADR-0307 §3:6 | Nothing: an answer still names no question; understanding infers which one (§3:1) |
| ADR-0315 §3:1 and §5's `RoundResponse`, `PlanningRound` and pydantic-ai completer rows | In the additions alone: the response names the calls its message asks about, the round records them, and the completer's reserved tool carries the naming beside the notes (§2:3, §2:8) |
| ADR-0276 §2:1 | `ProposedActivationUnderstanding`'s and `ActivationUnderstanding`'s field sets, in the additions alone: the answer pointer (§3:1). §7:7's *grants no authority* stands |
| ADR-0192 §1:1 | For an approval from a yes alone: it is spent when used, per question part, in the plan-store claim, whatever the declaration's idempotency (§4:9). The ledger's spending of a decision stands |
| ADR-0154 §4:1 | Nothing: §4:15 states how Condition 12 holds for a call that runs under an approval, the question ADR-0320 left to this milestone |
| ADR-0148 §8:4 | Nothing: ADR-0319 retired it; §2:4–§2:6 state what a question shows now |
| ADR-0098 §4 | Nothing: a yes is the user question its fourth clause names as a terminal ruling |
| ADR-0313 §5:2 | Whole: the grant listing and revoke members leave (§7:1) |
| ADR-0313 §8 | The ADR-0235 row's *the authority milestone redoes the act* (§7:1) |
| ADR-0319 §6:1 | Whole: §5:2 is `UserConfirmation`'s producer |
| ADR-0319 §6:2 | Its second limb: the structural test pins that the yes path is the only production producer |
| ADR-0319 §8 | The ADR-0193 and ADR-0235 rows' *the authority milestone redoes the act* (§7:1) |
| ADR-0193 | Every clause still in force but §6:3, §6:5, §6:8, §6:14, §6:20 and §11:1–§11:10: the grant, its store, its act, its coverage and its surfaces retire (§7:1). The authorisation pointer's pairing, the route (a) discriminator, `InvalidAuthorisationError` and the three-state rendering stand, since the configured-provider routes and route (a) use them |
| ADR-0235 | Whole: what §§1–14 still bind is the establishing act and its surfaces, which retire (§7:1), and `from_confirmation` (§4:13–§4:17, §12:22), which retires with them (§9) |
| ADR-0238 | §1, §6:1–§6:3, §6:5–§6:9, §7:3–§7:5, §12:3, §14:1, §14:6, §14:8, §15:8, §15:27 and §15:29, and §13:1's destination-trust limb: destination trust and route (b)'s closed-loop carve-out retire (§7:1–§7:2). `closed_loop` as the configured-provider routes' eligibility, the spend clauses, §3:2, §6:4 and §12:6 stand |
| ADR-0242 | Whole: what it still binds is the trust act's surface and its listing and revocation, which retire (§7:2) |
| ADR-0152 §7:1, ADR-0247 §7:1 | The count of what `rebind` takes from `approved`, in that count alone, which becomes five: `forecast_reach` (§4:16) |
| ADR-0260 §11:7 | *`EgressBinder.rebind` transcribes nothing new*, and *ADR-0152 §7's and ADR-0247 §7's count is untouched*: an approved forecast read is rebound (§4:16) |
| ADR-0247 §1:4, §6:9 | Their *destination trust is untouched* limbs (§7:2) |
| ADR-0247 §12:7, §12:9 | Their route-(b) limbs, validated against or read back after the grant store: a row carrying a digest is refused (§7:7). Their route-(c) limbs stand |
| ADR-0247 §12:17 | Whole: its subject, the trust store, is gone (§7:2) |
| ADR-0260 §6:5 | Its *destination trust is untouched* limb (§7:2) |
| ADR-0260 §6:6 | Its reliance on ADR-0193 §3 and §5 (§7:1); *no `RecipientGrant` is established, read, extended or implied* stands |
| ADR-0272 §3:7 | Whole: the recipient-grant seam it counts is gone (§7:1) |
| ADR-0236 §7:7 | Its premise of a real `RecipientGrants` holding a covering grant (§7:1) |
| ADR-0154 §4 condition 3 | Nothing superseded: the retiring lane re-attests it (§7:8) |

> **Normative.** This numbered draft records its replacements on the status lines and in a
> dated header note of ADR-0152, ADR-0192, ADR-0193, ADR-0235, ADR-0236, ADR-0238, ADR-0242, ADR-0247,
> ADR-0260, ADR-0272, ADR-0276, ADR-0306, ADR-0307, ADR-0313, ADR-0315 and ADR-0319,
> atomically with this ADR under ADR-0070 and ADR-0082, preserving their ratified bodies. The
> replacements take effect on this ADR's ratification.

## Consequences

**What becomes possible.**
- A call that needs you can run, once, on your yes, and every failure along the way ends in
  another question.
- `UserConfirmation` has a producer, so a memory the policy asks about can be kept.
- #2862's invented approval steps lose their cause: planning is told how approval works and
  what happened to each call.

**What it costs.**
- Every action in the world that the policy confirms asks once, including nearly every
  remember after a web search while the outside-content mark spreads
  ([#2856](https://github.com/leonapivato/ai-assistant/issues/2856)).
- Recipient grants and destination trust are gone until delegations replace them.

**What the outside-content design supplies later.** That design is a separate walk (#2856 and
its handoff), and nothing here decides it. Its direction: track who contributed to each value,
narrow model calls whose inputs code controls, a clean writer for outgoing text, scoped
delegations with an instruction as a temporary one, and credibility for belief only. The deploy
relies on it as follows, and nothing in the deploy slice reads the activation-level mark:

| The deploy would want | Supplied later by | Interim at the deploy |
| --- | --- | --- |
| Saving what you say without asking, after a web search | Per-fact provenance | `MemoryPolicy` asks, and your yes saves it |
| A confirmed memory keeping its source precisely | Source labels per fact | The outside-content mark plus the approval on the decision |
| Standing permission | Scoped delegations | None: every action in the world asks |
| Outgoing text outside content cannot shape | The clean writer | Every send shows its full text and asks |
| One web search not marking every later activation | Retiring the activation-level mark | The mark stays, failing safe |
| A direct instruction approving without a question | The instruction path | Every action the policy confirms asks once |
| "Why did you suggest that?" answered from sources | Sources of findings | None |

**Held, not decided.** Code-written sentences for the cases with no route ("your settings don't
allow this"; "this needs you, but I can't ask from here") are held until §8's #2862 runs show
whether planning's own wording is enough.

**What stays open.**
- The outside-content and provenance design, with #2856, #2798, #2846, #2847 and #2590.
- A price that comes back as a result is not checked against what was shown. Only the simulated
  booking charges at the deploy; a real paid capability needs the shown price to bind the call,
  by a maximum argument or a fresh quote checked before acting.
- The recheck after the lock ([#2586](https://github.com/leonapivato/ai-assistant/issues/2586)),
  unattended limits (#2583), other channels and voice identity (#2819, #2582, #113), voice itself
  (#2889), the numbers (#2589), and crash recovery of a claimed call (#2584).

## Alternatives considered

- **Code renders the whole question.** Rejected for the deploy: the owner preferred the model to
  explain the important facts in its own words. The exact line keeps what you see equal to what
  runs.
- **The model writes the question with no exact line.** Rejected: a mistake or a steered
  description would get your yes for something other than what runs.
- **Every value in custom displays, with tiers.** Rejected as over-built for now.
- **Code guaranteeing that every needs-you call is asked about.** Rejected: the model should ask
  on its own. #2862 came mainly from planning having no picture of how approval works and an
  instruction saying no route existed; §2:9–§2:10 address both.
- **A list of unanswered questions shown to understanding and planning.** Rejected: the window,
  recall and the story already show them.
- **Questions that open and close, or expire after a day.** Rejected: spending covers reuse, and
  staleness is a reading of the story.
- **A stored approvals table at the deploy.** Not needed: an approval is used only by its yes's
  activation. Stored approvals come with delegations.
- **Reading money back, or a stakes dial.** Rejected: money is not an exception, and
  double-checking is care, not permission.
- **Matching your words to exact values.** Not needed at the deploy, because a yes approves the
  values it was shown. It belongs to the instruction path.
- **Recipient grants redone now.** Rejected: delegations replace them.
- **Recording the approval outside route (a).** Not taken: `ActionPolicy.resolve` already keeps
  every ruling authored in `permissions`, and `AuditTrail.record` already checks a resolution
  against the confirm it answers.
