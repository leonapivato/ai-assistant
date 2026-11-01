# 323. A Telegram chat with the owner's bot is a line to the assistant, and connecting it approves what the line carries

- Status: Partially superseded by ADR-0330 (§2:1; §2:7, §5:5, §5:6, §5:7, §11:10 and §13:1 in their naming of Telegram as what the line's calls reach; §3:1; §3:3's *user's act*; §4:3; §11:4, §11:8 and §11:9 in the addition; §11:5; §12:1; §12:3 in the addition; §13's table, rows 3, 4, 5, 7, 8, 10 and 12; §14:1; §14:2 in the addition; each for a line in relayed mode alone) and ADR-0332 (§5:1, §5:8 and §6:11, each in the addition alone; §5:5; §5:7 and §8:1 whole: joining, the start wait, polling while an activation runs, and `/stop`) and ADR-0350 (§6:1's *the chat is the input's place*, for an activation the Task Scheduler starts) and ADR-0351 (§4:2, in *a forward's original sender*; §4:7, in the addition alone; §4:10's *its author is its original sender, claimed*; §4:11 whole) and ADR-0361 (§4:7, §4:8, §7:1 and §7:2, whole; §4:9, §6:1 and §12:2, each in the addition alone: the approval card, its edits and its tap)
- Date: 2026-10-17
- Scope: [#2819](https://github.com/leonapivato/ai-assistant/issues/2819), the messaging line, Telegram first; batch [#3113](https://github.com/leonapivato/ai-assistant/issues/3113), lane L1. It decides the Telegram kind on ADR-0292's model, how its calls leave the hub, and what they may carry.
- Dependency: the phases, the authority milestone (ADR-0321, ADR-0322) and the conversation channel (ADR-0293), all Accepted and built on `main` at `e3beb99d`.
- Authorization: the owner accepted proposal [#2820](https://github.com/leonapivato/ai-assistant/pull/2820) on 2026-10-17, after a review against `main` at `abf4e206`, with the conversion list recorded on [#2819](https://github.com/leonapivato/ai-assistant/issues/2819#issuecomment-6235969539). On the same day the owner ruled option (a) on this lane's stop ([#2819](https://github.com/leonapivato/ai-assistant/issues/2819#issuecomment-6238925310)). That ruling is the owner ruling ADR-0155 §3:3 reserves, taken under its arm (b), and this ADR is the ADR it commissions (§12). Every other ruling below is the owner's, from the walks of 2026-10-11 and 2026-10-17, each recorded on #2819. The dispatcher assigned 0323. This ADR is that proposal converted under `docs/proposals/README.md` → "When it is decided".
- **Changes `core`, so it is a contract-surface decision.** It adds the `telegram` channel type, a member of `ApprovalGiver`, the line's settings, a forward's author on the recorded input, and two Protocols, each landing as a triad (§15). Several shapes cross the wire, so `PROTOCOL_VERSION` advances.
- **Partially supersedes**, each in the scope §16 states and each for the line alone:
  [ADR-0155](0155-residency-governs-the-assistants-own-store-and-that-store-is-never-externalised.md) (§1:1, §1:3, §2:1, §3:2 and §3:3),
  [ADR-0148](0148-an-egress-call-is-authorised-as-one-whole-and-nothing-in-it-moves-after-the-ruling.md) (§1:1 and §7:1),
  [ADR-0154](0154-the-tools-egress-seam-is-designated-and-the-fourteen-conditions-are-attested-in-code.md) (§2:2's single-route limb, §2:4's standing-authorisation limb and §4:3),
  [ADR-0292](0292-a-channel-is-the-spokes-facing-one-thing-and-the-assistants-edge-is-its-own.md) (§10:1, in the addition alone) and
  [ADR-0321](0321-authority-at-the-deploy-is-your-yes-to-a-question-that-showed-the-call.md) (§3:3's second sentence, §4:4's *in one of your conversations* and §4:6's *through the hub chat*, each restated without naming a channel).
- Partially superseded: 2026-10-18 by ADR-0330 — for a line in relayed mode alone, which reaches a relay
  on the box holding one shared bot instead of the hub's own bot at `https://api.telegram.org`.
  §2:1: the bot is the shared one the person linked their account to. §2:7, §5:5, §5:6, §5:7,
  §11:10 and §13:1, in their naming of Telegram as what the line's calls reach: the relay stands
  in its place (ADR-0330 §4:16). §3:1: the credential is the hub's relay credential (ADR-0330
  §6:4). §3:3's *user's act*: the person's link act, which the settings the operator writes at
  their request carry out (ADR-0330 §11:4). §4:3: the user is established by Telegram's authentication as the relay hands on
  Telegram's report, and the reader still compares the sender with the setting (ADR-0330 §5:1).
  §11:4, §11:8 and §11:9, in the addition: they bind the relay credential (ADR-0330 §6:5–§6:6).
  §11:5: the one origin is the configured relay origin, verified against the configured
  certificates (ADR-0330 §3:4, §7). §12:1: the approval rests on the person's link act, carried
  out by setup at their request (ADR-0330 §11:1); §12:3, in the addition: unlinking ends it
  (ADR-0330 §11:3). §13's table, rows 3, 4, 5, 7, 8, 10 and 12: restated for the relayed route
  (ADR-0330 §9:2). §14:1 and §14:2: the relay's costs, and what it holds (ADR-0330 §10:3–§10:4).
  A line in direct mode, and every other clause, stand. This replacement takes effect on
  ratification of ADR-0330. This reciprocal header record accompanies the numbered draft under
  ADR-0070 and ADR-0082; the ratified body below is preserved.
- Partially superseded: 2026-10-21 by ADR-0332 — §5:1, in the addition alone: a `/stop` command is not input (ADR-0332 §8:3). §5:8, in the addition alone: the reader records a `/stop` command as an update it answered (ADR-0332 §8:6). §5:5: a message sent while an activation runs joins it where ADR-0332 §3:3 allows, after a fixed start wait (ADR-0332 §5:3). §5:7 whole: the reader keeps polling while an activation runs, paced (ADR-0332 §8:7, §8:8). §6:11, in the addition alone: the line's fixed answer to `/stop` (ADR-0332 §8:5). §8:1 whole: the line takes `/stop` (ADR-0332 §8:1–§8:6). Every other clause stands. This replacement takes effect on ratification of ADR-0332. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-25 by ADR-0350 — §6:1's *the chat is the input's place*, for an activation the Task Scheduler starts: the chat is a place on its place list wherever the line is connected, and the writer still refuses any chat but the one the settings name (ADR-0350 §5:11, §6:7). Every other clause stands. This replacement takes effect on ratification of ADR-0350. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-25 by ADR-0351 — §4:2, in *a forward's original sender*: it is the forward's party, claimed, not an author (ADR-0351 §2:7). §4:7, in the addition alone: input approves only where its parties are also the user alone, and understanding has not marked it relayed, so a yes that comes in with a forward, or in a paste, approves nothing (ADR-0351 §6:3, §6:5). §4:10's *its author is its original sender as Telegram reports it, claimed*: its author is the person who forwarded it, and the original sender is its party, claimed; it still informs and authorizes nothing (ADR-0351 §4:2). §4:11, whole: the kind declares the parties of each message in place of an origin per input (ADR-0351 §3:1). Every other clause stands. This replacement takes effect on ratification of ADR-0351. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-10-31 by [ADR-0361](0361-approvals-are-cards-the-person-taps-and-a-yes-is-a-one-time-ticket-for-the-exact-call.md) — §4:7, §4:8, §7:1 and §7:2, whole: no input on the line approves anything, and approving is a tap on a card. §4:9, in the addition alone: `ApprovalGiver` gains a member for each surface's tap. §6:1's *the chat is the input's place*, for a card: any activation's approval card is posted into the chat. §12:2, in the addition alone: the approval also covers posting a card, editing it and answering a button's callback, for the one chat the settings name (ADR-0361 §4). Every other clause stands. This replacement takes effect on ratification of ADR-0361. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.

## Context

**The question.** How do you message the assistant from anywhere, and get its answer there,
through a Telegram chat with a bot of your own?

**The direction** (owner, 2026-10-11, on #2819). This is a line *to* the assistant, not the
assistant acting in your chats with other people. Telegram comes first. A carrier line, through
an API such as Telnyx with RCS where the phone supports it and SMS as the fallback, comes later.
Hosted iMessage is not pursued for now. The proposal was walked in three passes on 2026-10-11 and
accepted on 2026-10-17.

**What is built on `main` at `e3beb99d`.**
- The code knows two channel types, `conversation` and `informational_event`. Their input
  origins are declared in `_INPUT_ORIGINS` in `core/channel_validation.py`. There is no channel
  kind object or registry.
- `ChatReader` and `ChatWriter` in `orchestration/chat.py` are the hub chat's spokes, and the
  pattern this kind copies (ADR-0293).
- Questions are ordinary messages with an exact line, answered by a typed reply that
  understanding reads (ADR-0321 §2, §3; ADR-0322).
- Authorizing reads whether an input carries the user's authority from one flag,
  the `users_authority` flag of `PhaseWorking` in `orchestration/phase_path.py`. Its docstring cites ADR-0321
  §3:3: "only a message the user sent through the hub chat does". The approval's *who* is
  `ApprovalGiver.USER_THROUGH_HUB_CHAT` in `core/types.py`.
- Connected accounts exist and are used by web search, forecasts and sending email. Each is used
  through a setting that names the account's reference, and its credential is in the OS
  keyring (ADR-0149, ADR-0151).
- `HttpsExchange` in `tools/egress.py` sends "A GET, and no other method", which
  [#2076](https://github.com/leonapivato/ai-assistant/issues/2076) parks for the first
  integration that writes.
- Nothing reaches Telegram.

**What the conversion found.** On a first reading against `main`, the proposal's "every call to
`api.telegram.org` passes the egress seam" collides with the egress corpus.
- Every message the assistant writes is planning's output, and planning was given the
  assistant's own store: its window, recall and memory. That makes the message covered content
  under ADR-0155 §3:1.
- ADR-0155 §3:3 forbids covered content in a span at the designated `tools/` seam where every
  covered path has a model call on it. It reserves any relaxation to an owner ruling and a
  commissioned ADR.
- ADR-0155 §3:2 forbids such content outright where a path has no model call, and says no
  authorisation cures it. The *couldn't finish* message, which lists effects from the records,
  is such content.
- ADR-0155 §1:1 forbids placing any part of the store in a service another party operates, and
  Telegram keeps the bot chat on its servers.
- ADR-0148 §1:1 allows no second route to the seam, ADR-0148 §7:1 reads a credential only inside
  a callable `ToolInvoker.invoke` reaches, and ADR-0154 §2:2, §2:4 and §4:3 admit no standing
  authorisation.

The owner was given the question and a privacy assessment, and ruled option (a): a Telegram
line the owner connects as their own private place counts as theirs. The line writer's
messages, written only to the one configured chat, may carry covered content. The cost is
stated plainly (§14).

## Decision

We will build Telegram as a channel of its own: one bot the owner connects, one private chat
with it as the place, and a reader and a writer in the hub that reach Telegram through the
designated egress seam on a route of their own. The connect act and the settings are the
approval that lets what the assistant writes reach that one chat.

### 1. Status and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree.

> **Normative.** No lane implements this decision until it has merged `Accepted`. Its lanes are
> cut then, under the Telegram milestone the owner ruled on 2026-10-17.

### 2. The shape

| | The hub chat (ADR-0293) | Telegram |
| --- | --- | --- |
| **Medium** | The hub's chat space, hosted by the hub | Telegram, held by Telegram |
| **Place** | A conversation | Your private chat with the bot |
| **Spoke** | The chat's reader and writer, in the hub | The bot's reader and writer, in the hub |
| **Channel** | `conversation`, built in | The bot's channel, created by connecting it |
| **Your end** | The devices you chose for the conversation | Telegram on your phone, and any other Telegram app signed into your account |

> **Normative.** The Telegram kind's medium is Telegram, and its place is a private chat between
> the user's Telegram account and a bot the user connected.

> **Normative.** The kind's spoke is in the hub: a reader, which is its sensor, and a writer,
> which is its actuator (ADR-0292 §2:13). Both reach Telegram only through §11's route.

> **Normative.** One channel exists for each connected bot that the line's settings name (§3),
> keyed by its connection's reference, and its place is keyed by the chat's id. Its channel
> identity is (`telegram`, that reference with that chat id), read as (that bot's channel, that
> chat) the way ADR-0292 §10:8 reads the conversation's identity, and every read of the place,
> its window and its message positions included, is keyed by both.

So a change of the configured account, or a new bot connected for the same account, is a new
place: the old chat's history does not run on as if it were the same conversation.

> **Normative.** The user's Telegram apps are the user's end of the chat. They are not devices
> of the hub and not spokes, and no device role, "my devices" included, reaches them.

> **Normative.** Telegram is not a hosted medium. The hub keeps no copy of the chat, and its
> record of the line is the episodes: what came in and what the assistant wrote (ADR-0292 §3:2).

The episodes are not kept in step with Telegram. They differ where the assistant perceived
something differently:

| | Telegram's copy | The episodes |
| --- | --- | --- |
| You edit or delete a message in Telegram | Changes | Stays as received |
| You forget something in the assistant | Stays | Removed |
| Voice notes and photos, for now | There | Absent |
| Messages lost in an outage over 24 hours (§5) | There | Absent |

> **Normative.** The line shares no transcript with the hub chat. What connects the two is the
> assistant's memory: the episode window, recall and stories.

> **Normative.** The hub always calls out to Telegram, and Telegram never connects to the hub.
> No webhook is built, so the line needs no public address.

### 3. Setting it up

1. **Create the bot** with Telegram's @BotFather, which gives you its token.
2. **Connect it** with `assistant connect`, giving the token as the credential.
3. **Name the line and yourself in settings**: the connection, and your Telegram user id, which
   a bot such as @userinfobot shows you.
4. **Turn on Telegram's two-step verification** for your account (§14).

> **Normative.** The bot is connected with `assistant connect`, as any connected account is
> (ADR-0149, ADR-0151). Its token is the credential, kept in the OS keyring under the reference
> the hub mints, and entered only where ADR-0177 lets a credential be entered.

> **Normative.** Two settings name the line: `telegram_connection`, the connection's reference,
> and `telegram_user_id`, the user's Telegram account id. Setting one without the other is
> refused at settings load.

> **Normative.** The line exists only while both settings are set and the connection they name
> is active. Setting them is the user's act that creates the channel (ADR-0292 §2:6), declares
> its audience private (ADR-0292 §9:6), and names the one chat the line may write to (§12).

> **Normative.** The setup instructions name an OS credential service on the hub as a
> prerequisite of `assistant connect`, and recommend Telegram's two-step verification. The hub
> neither checks nor enforces the second.

On a box with no credential service, `assistant connect` fails
([#1161](https://github.com/leonapivato/ai-assistant/issues/1161)). That is a setup fact, not a
design one.

> **Normative.** The account is named by the setting, and no pairing flow is built.

Pairing from a device with a one-time code is worth building when someone other than the owner
sets a line up (What it leaves open).

> **Normative.** Disconnecting removes the token (ADR-0151 §8). The channel stays, unreachable,
> with its episodes (ADR-0292 §2:8), and planning is told it is unavailable (ADR-0292 §2:9).

Forgetting what was said on the line is the ordinary forget, over its episodes.

### 4. Authors and authority

**Authentication.** The kind says how sure it is of an author, and nothing more.

> **Normative.** A message on the line whose sender is the account `telegram_user_id` names,
> sent in its private chat with the bot and not forwarded, is the user's, established.

> **Normative.** Every other author an input on the line carries is claimed: a forward's
> original sender, and the author of a message a reply quotes where the assistant did not
> write it.

> **Normative.** The line establishes the user by Telegram's own authentication of its users:
> the reader compares the sender id Telegram reports against the setting, and adds no
> authentication of its own. "How sure" is established or claimed, never another value.

> **Normative.** Content never establishes the user on the line. A message saying it is from
> the user is claimed like any other where its sender is not the configured account
> (ADR-0292 §5:8).

**Authorization.** Authorizing never learns which channel an input came on.

> **Normative.** Authorizing reads only whether the input carries the user's authority, a fact
> the channel's intake sets from its kind's author declaration. No authorizing rule names a
> channel, so a later channel declares how it establishes authors and changes no rule of
> authorizing.

> **Normative.** An input on the line carries the user's authority only where every message it
> takes in is the user's, established, and none is a forward.

A message you send to the bot is sent as an instruction, exactly as a message in the hub chat is
(ADR-0293 §4:8). So the line is as safe as your Telegram account (§14).

> **Normative.** ADR-0321 §3:3's second sentence reads, for every channel: input approves only
> where its author is one its channel's kind establishes as the user and it was sent as an
> instruction. An email, an event or a forward saying yes approves nothing.

> **Normative.** ADR-0321 §4:4's *shown to you* holds where the question's message has a done
> delivery record in a place whose kind establishes the user as an author there: one of the
> user's conversations, or the line's chat.

> **Normative.** ADR-0321 §4:6's *who* is the user through the channel the yes came on, and
> `ApprovalGiver` gains a member for the line beside `USER_THROUGH_HUB_CHAT`.

**Forwards.** Telegram marks a forward with who wrote it.

> **Normative.** A forward is input, and its author is its original sender as Telegram reports
> it, claimed. It informs and authorizes nothing, and what the user writes beside it is the
> user's.

> **Normative.** The kind declares an input's origin per input (ADR-0284 §2:2): `outside` for an
> input that takes in a forward, and `user` for every other. An input that takes in a forward is
> therefore an outside trigger (ADR-0306 §4:5), its recorded trigger carries the forward's
> author, and the activation has read outside content.

That has a cost, and the owner accepts it. What you write beside a forward is taken in with it,
so it is read as outside too. After a forward, a remember of what you said is asked
about and a call that leaves the hub needs you, because the outside-content mark is the
activation's ([#2856](https://github.com/leonapivato/ai-assistant/issues/2856)). That redesign is
the owner's for later, and nothing here designs it.

**Replies.** Telegram sends a reply with the message it replies to.

> **Normative.** The reader brings a replied-to message in as quoted context with its author:
> the assistant where the bot wrote it, the user where the user did. Like the window, it
> informs and never authorizes (ADR-0292 §10:3).

> **Normative.** Where the replied-to message is one the writer sent, the reader links it to the
> activation that wrote it by that message's effect record (ADR-0303 §7:1), so understanding
> sees which message a reply is to.

### 5. What comes in, and when

| Event in Telegram | Input? |
| --- | --- |
| A text message from your account, in your private chat with the bot | Yes, a push |
| A message you forward | Yes, with its original sender as its author (§4) |
| Anything from any other account or chat | No. Ignored, and not recorded |
| You editing or deleting a message | No |
| A voice note, photo, file, sticker or location from you | No. The bot answers with a fixed line, and nothing starts |

> **Normative.** The kind's input is a text message, or a forward, from the configured account in
> its private chat with the bot (ADR-0292 §6:9). Nothing else in Telegram is input.

> **Normative.** An update from any other account or chat is not input: it starts nothing, is
> recorded nowhere, and the bot does not answer it.

> **Normative.** A non-text message from the configured account starts nothing, and the writer
> answers it by rule with the fixed line "I can only read text here for now."

That fixed line plays the part of the hub chat's refused send (ADR-0293 §4), since Telegram gives
a bot no way to refuse a message. `/start`, which Telegram sends when you first open a bot, is an
ordinary message.

> **Normative.** Each message keeps the time Telegram gives it, so messages taken in together
> stay separate and dated in the episode.

**One activation at a time.** ADR-0292 §11:5's interim is stated for a conversation; this kind
rules it for its own chat.

> **Normative.** The line's chat runs one activation at a time. A message sent while one runs
> waits in Telegram and is never refused, and when that activation ends everything waiting is
> taken in together as one input.

> **Normative.** The reader confirms an update to Telegram only once it is dealt with: input once
> its activation is admitted; an update that is not input once it is seen; and a non-text
> message once the intake record shows it answered (§5:3).

> **Normative.** The reader asks Telegram for nothing while an activation started from the chat
> runs.

This is ADR-0292 §11:5's "lands in the medium and waits", with Telegram as the medium.

**The intake record.** The reader's bookkeeping, as the hub chat's is (ADR-0293 §6:6–§6:9).

> **Normative.** The reader records which updates it took in, by their Telegram update ids, and
> by which activation, and which non-text messages it answered, holding no message text.

> **Normative.** An update taken in or answered once is never taken in or answered again: a
> duplicate fetch starts no second activation and sends no second fixed line.

> **Normative.** After a restart, updates an interrupted activation already took in are not
> taken in again, and updates never taken in are taken in as usual.

> **Normative.** The reader's contract does not assume polling. What the reader owes the channel
> is new input with its author and its time, and whether a spoke polls or takes webhooks is the
> spoke's own.

**What waiting in Telegram costs.** Telegram keeps an unconfirmed update for 24 hours. Messages
you send while the hub is down for longer are lost, and the hub cannot tell. Every bot has this
limit, wherever it runs.

### 6. What goes out

> **Normative.** The writer sends the activation's messages to the line's chat, and only there.
> The chat is the input's place (ADR-0306 §4:7), and the writer refuses, before any byte is
> sent, a message for any chat but the one the settings name.

Writing to Telegram first, as a reminder does, comes with the timers and proactivity milestone,
when planning chooses where output goes (ADR-0292 §7:2).

> **Normative.** A message is *sent* when Telegram accepted it and returned its message id. That
> id is the message's position on its effect record (ADR-0292 §7:4, ADR-0306 §5:5).

**When a send fails.**

> **Normative.** The writer retries a send only where Telegram did not get it, because the
> request was never written, or where Telegram answered that it was not sent and a retry can
> succeed, as with a rate limit.

> **Normative.** A request that was written and got no answer is recorded *unknown* and never
> retried: Telegram cannot recognize a repeated message, so a retry could deliver it twice
> (ADR-0306 §5:13).

> **Normative.** Every other refusal Telegram answers with is recorded *not done*, and is not
> retried.

Either way the outcome is on the effect record, so the next activation sees in its window that a
reply may not have reached you.

**Text.**

> **Normative.** The writer sends plain text, and the kind's description tells planning that the
> chat shows plain text.

> **Normative.** A message longer than Telegram's 4,096 characters is sent as consecutive parts,
> none longer than that, together holding the whole text in order. It is split at paragraph
> breaks; a paragraph longer than a part is split at line breaks, then between words, and at the
> limit only where a run of text has no break. The episode records one message. Its effect record never records
> done for a part Telegram did not accept, and how a message cut short between parts is
> recorded is the implementation's, within ADR-0306 §5:5.

**Working.** While an activation runs, the bot shows Telegram's "typing…".

> **Normative.** While an activation started from the chat runs, the writer renews Telegram's
> typing indicator until it ends. That is the assistant's current state shown to your end, and
> it is never written into the chat (ADR-0292 §11:7).

**Endings.**

> **Normative.** An activation started from the chat writes the fixed *couldn't finish* message
> into the chat in exactly the cases, and in the form, ADR-0317 §2–§3 decide for a
> conversation.

> **Normative.** After a restart, for a chat whose last activation the restart cut off, the
> writer sends one fixed message by rule: "I was interrupted before I could answer. Send it
> again if you still need it."

The hub chat stays silent after a restart and shows *interrupted* in its current state
(ADR-0293 §9:2). Telegram has no such state to show, and without the message you would see
"typing…" and then nothing.

> **Normative.** A stopped activation writes nothing new into the chat (ADR-0295 §3:3).

### 7. Questions and answers

> **Normative.** A question on the line is the ordinary message ADR-0321 §2:12 and ADR-0307 §3:6
> make it: plain text with its exact lines, no buttons and no options.

> **Normative.** An answer on the line is a typed message. It is read under ADR-0321 §3 and
> ADR-0322 §2 as any answer is, and replying to the question's message is the strong hint
> ADR-0321 §3:4 names.

One reply can approve several questions on the line as it can in the hub chat: "both", or "all of
them", read over the questions understanding sees in its window, recall and stories, each under
its own approval (ADR-0322 §2:2, §3:2). A yes typed in Telegram can answer a question asked in the
hub chat, and the other way round, through recall and the story.

Buttons as reply shortcuts, sending a fixed typed answer when tapped, are a later option. This
decision supersedes nothing for them.

### 8. Stopping

> **Normative.** The line has no stop command. Typing "stop", or "scratch that", in Telegram is a
> message like any other (ADR-0292 §12:6), and under §5's interim it waits until the running
> activation ends.

The intended path is a follow-up such as "scratch that", read by understanding
([#2515](https://github.com/leonapivato/ai-assistant/issues/2515), owner's comment of
2026-10-17). Under the interim it can withdraw what is still pending, such as an unanswered
question or a step not yet run, but it cannot halt work mid-run. ADR-0295 is unchanged.

### 9. What the kind declares

In ADR-0292's vocabulary:

| What a kind declares (ADR-0292) | Telegram |
| --- | --- |
| Its channels (§2:5–§2:6) | One for each connected bot the line's settings name, created by connecting it and naming it |
| Its spokes and directions (§2:11) | One spoke in the hub: the reader, its sensor, and the writer, its actuator; in and out |
| Pulled, and pushing (§6:5) | Pushes: your messages and forwards. It cannot be pulled, because a bot cannot read a chat's history |
| Which events are input (§6:9) | §5:1: text messages and forwards from your account, in its private chat |
| Its push filter (§6:11) | None |
| How it establishes authors (§5:4) | §4:1–§4:3: your account, not forwarding, is you, established; every other author is claimed |
| Places (§2:1, §10:8) | Each private chat with the bot, keyed by its chat id |
| Its window (§10:2) | §10: the recent episodes on the channel and place, as many as the conversation's window holds |
| What counts as sent (§7:4) | Telegram accepted it and returned its message id |
| Its description (§8:1) | A private Telegram chat with the user, shown as plain text, whose own messages carry their authority, and which expects a reply, a question or a notice. Plus what the user wrote about it when setting it up |
| Its requirements (§8) | Not a hosted medium, so no medium's rules. The channel's rules at the writer: text only, and only to the configured chat. The spoke's limits: 4,096 characters a message |
| Its audience (§9) | Private, declared by setting the line up (§9:6). Whether text shows on your lock screen is your Telegram setting (§9:7). What may be said is ADR-0199's, as for the hub chat |

> **Normative.** The Telegram kind declares what the table above states, each row in the
> ADR-0292 clause its first column names.

> **Normative.** The channel's rules are enforced at the writer, before anything leaves, whatever
> a model produced (ADR-0292 §8:3): text only, and only to the chat the settings name.

### 10. The window

ADR-0292 §10:1 brings the window in from the medium wherever the medium holds a history, and
ADR-0303 §7:10 lets a kind whose medium has no stable item ids declare an episode window.
Telegram's chat has a history with stable ids, but a bot cannot read it, so neither covers it.

> **Normative.** A kind whose sensor cannot read its medium's history may declare an episode
> window: its place window is then the recent episodes on that channel and place, each linked to
> the activation it records.

> **Normative.** The Telegram kind declares an episode window.

### 11. The line's route through the egress seam

User data leaves the hub only through `models/`, the designated `tools/` seam or the remote
transports (ADR-0124 §1:1, ADR-0174 §1:1). The line goes through the seam.

> **Normative.** Every call to Telegram's Bot API is made in `ai_assistant.tools.egress` and in no
> other module (ADR-0154 §1). The reader and the writer reach it only through a Protocol in
> `core/protocols.py` whose one production implementation is there.

> **Normative.** The line's calls are not egress calls in ADR-0148's sense. No `ActionRequest`,
> `EgressBinding` or policy ruling is made for them, and the rules this section and §13 state
> stand where ADR-0148's per-call machinery would.

> **Normative.** The line reaches the seam by its own route, and by no other. An activation's
> message is sent only after ADR-0306 §4:7's place check has passed and its effect record has
> been claimed (ADR-0306 §5:4). Every other call is made only after its own record has been
> claimed (§13:2). Every message, of either kind, goes only to the chat the settings name.

> **Normative.** The bot's token is read inside `ai_assistant.tools.egress`, through the
> `INTEGRATION`-scoped `Secrets` face (ADR-0125 §8), only after the call's record has been
> claimed and, for a message, its checks have passed, and only while the line is configured and
> its connection active. It is read once per call, with
> the connection record read before it and again before any byte is sent, as
> `HttpsEgressTransport.fetch` does (ADR-0148 §6).

> **Normative.** The line reaches one origin, `https://api.telegram.org`, fixed in code and never
> configured, with no redirect followed (ADR-0231 §5's properties of `HttpsExchange`).

**The method ([#2076](https://github.com/leonapivato/ai-assistant/issues/2076)).** Sending a
message is a write, and so is confirming an update, which a poll does by its offset.

> **Normative.** `HttpsExchange` gains one body-bearing request, a `POST` with a JSON body and
> its `Content-Length`, used by the line's route alone. The search and the forecast keep their
> `GET`, and their declarations are unchanged.

> **Normative.** Every Bot API call the line makes is a `POST`.

This settles #2076. It closes when the lane that widens the exchange merges.

**The token in the path.** The Bot API takes its token in the request path:
`https://api.telegram.org/bot<token>/<method>`.

> **Normative.** The seam binds the token into the request target itself, after the credential
> read, and no caller of the seam ever holds the target.

> **Normative.** Nothing that records a request target records the line's: no log line, trace,
> audit or effect record, exception message, `repr` or error text carries it, or any part of
> the token.

**The long poll and the deadlines.** The seam has no timer of its own: the caller's bound limits
the wait (ADR-0029 §4, ADR-0241 §1).

> **Normative.** Each poll asks Telegram to hold the request open for at most a configured wait,
> and is handed a bound, required and with no default, that exceeds that wait by a margin and
> covers the poll's whole work.

> **Normative.** A poll that reaches its bound is cancelled and its channel closed, its record's
> outcome is unknown, and the reader polls again. It takes nothing in, and the offset it sent
> can have confirmed only updates already dealt with (§5:6).

> **Normative.** Each send is handed a bound of its own. A send cut off by its bound after its
> request was written is *unknown* (§6:4).

> **Normative.** Every response is read under a read bound the line's settings declare, refused
> beyond it as `HttpsExchange` refuses every response beyond its bound.

> **Normative.** Each call opens its own channel and closes it, and the seam holds no pool and no
> connection across calls (ADR-0191 §3).

### 12. The approval surface ADR-0155 §3:3 commissions

ADR-0155 §3:3 reserves to an owner ruling whether to commission "a later ADR that designs a
content-bearing approval surface compatible with ADR-0150 §10 and states its privacy
consequences". The owner chose that arm for the line on 2026-10-17. This ADR is that ADR.

**The surface is the connect act.** It is two acts, both the owner's and both recorded: connecting
the owner's own bot (ADR-0151), and naming the owner's own account in settings. Together they
approve one thing: what the assistant writes to its user on this line may reach that one chat,
whatever store it came from. They are the content-bearing approval because what they approve is
the content's destination as the user's own private place, rather than one call's bytes.

> **Normative.** The connect act and the line's two settings are the approval that lets the line's
> calls carry covered content, under ADR-0155 §3:1's definition, to the one chat the settings
> name. Delivery anywhere else is refused at the writer as the channel's rule (§9:2).

> **Normative.** The approval covers the line's calls alone: the writer's messages and typing
> indicators to that chat, and the reader's polls of the bot. It covers no egress call, no
> capability and no other destination.

> **Normative.** The approval ends when the connection is disconnected or either setting is
> unset, and nothing the line sends after that is covered.

**Compatible with ADR-0150 §10.** §10 governs the payload description an egress call is ruled on:
it holds no content, names no record, and no rendering stands in for it. The line's calls carry
no binding and no description (§11:2), so §10 has nothing to reach on them, and this surface
leaves it whole for every egress call.

> **Normative.** The line mints no payload description, adds no member to `EgressBinding`,
> `ConfirmationEgress` or `PermissionDecision`, and puts no record identifier into anything it
> sends.

**What the line places in Telegram** (ADR-0154 §6:2 and ADR-0155 §6:2–§6:3, stated for the line).
Its ordinary operation does place the owner's data in a service another party operates. The
writer's messages, which can carry anything the assistant knows, are kept in the chat on
Telegram's servers. Under ADR-0155 §3, three kinds of content reach Telegram:
- a message's text, which planning wrote;
- the fixed messages, *couldn't finish* listing effects from the records among them;
- a poll's update offset, which the intake record holds.

This decision admits all three, for the one chat, and nothing else keeps them out.

### 13. ADR-0017 §3's fourteen conditions, on the line's route

ADR-0154 §4:1 designates the seam on these conditions holding in code, and a change that falsifies
one owes an ADR. This is that ADR for the line's route. Each row states what the line's
implementation holds in code.

| # | Condition | How it holds on the line's route |
| --- | --- | --- |
| 1 | A named seam and an import-linter contract | The Bot API client is in `ai_assistant.tools.egress`, and the contract confining network transports there is unchanged (§11:1) |
| 2 | Per-call gating before transmission | Each message passes the place check, the claim and the channel's rules before a byte is sent (§11:3, §9:2) |
| 3 | Recipient authorisation traced to a user act | The one chat is the owner's recorded acts: the connect act and the settings (§12:1) |
| 4 | Credential access gated | The token is read only inside the seam, after the gates, with the record re-read before sending (§11:4) |
| 5 | Transport pinned, no redirect | One origin fixed in code, no redirect, TLS checked before any write (§11:5) |
| 6 | The payload bound before transmission, described after | The message sent is the one the claimed effect record names, recorded in the episode |
| 7 | A named approver able to refuse | The owner, whose refusal is standing: disconnecting or unsetting refuses every later call (§12:3). There is no per-message confirmation, on the owner's ruling |
| 8 | What is transmitted is bound to what was authorised | The writer sends the recorded message to the configured chat, and nothing a model wrote names the chat |
| 9 | Multi-recipient calls as one set | One recipient, always: a send to any other chat is refused (§6:1) |
| 10 | Destinations canonicalised | The origin is compared exactly, and the chat id is compared for equality with the setting |
| 11 | Resolving a name is gated or forbidden | Forbidden: the line resolves no username, and the account id is the owner's setting |
| 12 | An attempt identifier and an explicit outcome | Every call is claimed by a durable record before it is sent, and completed with its outcome. An activation's message has its effect record (ADR-0306 §5:3–§5:5). A fixed reply, a typing indicator and a poll each have a record of the line's own (§13:2) |
| 13 | Payload classification settled | By §12: the line's calls may carry covered content to the one chat |
| 14 | Failure paths tested | §15:5 |

> **Normative.** Each row of the table above holds in code on the line's route before the line's
> first call reaches Telegram, and the lane that builds the route attests each row in its change.

> **Normative.** Every call the line makes other than an activation's message, a fixed reply, a
> typing indicator or a poll alike, is claimed before it is sent by a durable record of the
> line's own, carrying an attempt identifier, and completed with its outcome: done, not done or
> unknown. A record left with no outcome, as after a crash, is never resolved by guessing.

How long a poll's or a typing indicator's record is kept is the implementation's. Like
every record of the line, it is the user's data and is purged with it.

### 14. What it costs in privacy

The owner ruled this cost acceptable on 2026-10-17. It is stated plainly here, and in the setup
instructions.

- **Telegram can read the chat.** A bot chat is not end-to-end encrypted. Telegram's servers
  carry every message both ways and keep the chat until you delete it there. Anything the
  assistant writes on the line, from any memory, is in that copy.
- **Telegram discloses to courts.** Since September 2024, Telegram's policy is to disclose a
  user's IP address and phone number in answer to a valid court order.
- **Account takeover is the practical risk.** The line is as safe as your Telegram account:
  whoever controls it is you, established, to the assistant (§4). Telegram's two-step
  verification guards against that, and setup recommends it. The hub cannot check that it is on.
- **The token is the line.** Whoever holds the bot token can read what is sent to the bot and
  send as it. It is kept in the keyring. To change it, revoke it with @BotFather and connect
  again (ADR-0151).
- **Forgetting reaches what the assistant reads, not Telegram.** Forgetting an episode keeps it
  out of every later activation. Telegram's copy stays until you delete it there, and the hub
  cannot reach it (ADR-0155 §5:3).

> **Normative.** The setup instructions state each cost in the list above before the line is
> connected.

> **Normative.** No clause, surface or message of the line states or implies that the hub can
> reach, bound or delete Telegram's copy of the chat.

### 15. How it is built

> **Normative.** The line's lanes are cut at its contract seams as ADR-0137 decides, and each
> lane that consumes a contract is briefed only after the lane landing that contract has merged
> (ADR-0137 §4:1). They run back to back in one milestone, with no other design waited on
> between them, and the line goes live in the deploy after the last of them.

> **Normative.** No Telegram library is added. The Bot API is a handful of HTTPS calls returning
> JSON, made through the seam's own exchange.

A library would bring its own HTTP stack, which would have to be kept behind the seam.

| What | Where | Change |
| --- | --- | --- |
| The `telegram` channel type | `core/channel_validation.py`'s `_INPUT_ORIGINS` and the admission table | New, its origin declared per input: `outside` where the input takes in a forward, `user` otherwise (§4:11) |
| A forward's author | The recorded input (`RecordedChannelTrigger` and what it carries) | Carries each forward's original sender, claimed (§4:10–§4:11) |
| `ApprovalGiver` | `core/types.py` | Gains a member for the line (§4:9) |
| The line's settings | `core/config.py` | `telegram_connection`, `telegram_user_id`, the poll's wait, and the line's bounds (§3:2, §11) |
| The Bot API client | A new Protocol in `core/protocols.py`, implemented in `tools/egress.py` | New: polls, sends and the typing indicator, on §11's route |
| The intake record | A new Protocol in `core/protocols.py`, with its store | New: §5:8–§5:10 |
| `HttpsExchange` | `tools/egress.py` | Gains the `POST` with a JSON body (§11:6) |
| The reader and the writer | `orchestration`, beside `ChatReader` and `ChatWriter` | New, run as a long-running task in the hub |
| `PhaseWorking`'s `users_authority` flag | `orchestration/phase_path.py` | Set from the line's intake as §4:5–§4:6 state; its docstring's hub-chat wording follows §4:7 |
| `AuthorizingStage._delivered` | `orchestration/authorizer.py` | *Shown to you* reads §4:8's places |
| The kind's declarations | Where the first kind declared in code puts them | §9 |

> **Normative.** The `core` additions the table names land as it states. Each new Protocol lands
> as a triad, with its conformance suite and canonical fake, together with its primary
> implementation (ADR-0137 §2). Exact names and shapes are the implementing lane's, within the
> table.

> **Normative.** Each change to a shape the wire carries advances `PROTOCOL_VERSION` on
> ADR-0124 §9's rule.

> **Normative.** The line is tested against a fake Telegram, never the real one: each failure
> rule of §6, a chat other than the configured one refused before any byte, a redirect refused,
> an update from another account ignored, a duplicate update taken in once, and no token in any
> log line, record or error.

The owner's ruling of 2026-10-11, both halves together and no switched-off code, is kept so: a
part of the line sits in the tree only while the next lane of the same milestone is built.

**Voice notes** are the first follow-up after the line is built. The hub transcribes them, and
their author is still you, established. Live speech, with its audience questions, stays with the
voice work ([#2578](https://github.com/leonapivato/ai-assistant/issues/2578)).

### 16. Relationship to earlier decisions

| Earlier decision | What changes |
| --- | --- |
| ADR-0155 §3:3 | For the line alone: covered content all of whose covered paths have a model call on them may be carried by the line's calls to its one chat, under §12's approval. This ADR is the commissioned ADR its arm (b) names. Every other span at the seam stays forbidden as written, with ADR-0233's and ADR-0238's exceptions |
| ADR-0155 §3:2 | For the line alone, on the owner's ruling: covered content with a path that has no model call on it may be carried by the line's calls to its one chat. *No authorisation cures it* stands for every other span |
| ADR-0155 §1:1 | For the line alone: the line's calls place covered content in Telegram's copy of the chat. Every other part of the store stays out of every other party's service |
| ADR-0155 §1:3 | For the line alone, in the addition: Telegram's copy of the chat, kept as the ordinary consequence of the line's calls, is outside the residency clause, as a copy kept after an egress call authorised under §2 is |
| ADR-0155 §2:1 | For the line alone, in the addition: content may also leave through the seam on the line's route (§11), under §12's approval, and not as an egress call authorised per call |
| ADR-0155 §3:4, §5:3, §6 | Nothing. §3:4 is stated over a transmission the prohibitions forbid, and for the line they forbid nothing. §5:3 is applied (§14:2), and §12 makes §6's statements for the line |
| ADR-0148 §1:1 | For the line alone: the line's calls reach the seam by its own route (§11:3), not from a callable `ToolInvoker.invoke` reaches. *None may be added by configuration, by a declaration, or by an integration constructing its own client* stands, and the route is added by this ADR alone |
| ADR-0148 §7:1 | For the line alone: the bot's token is read inside the seam after the line's own gates (§11:4), not inside a `ToolInvoker` callable. §7:2–§7:6 stand |
| ADR-0148 §9:1 | Nothing: ADR-0306 and ADR-0319 already replaced it whole. The line's attempt and outcome are each message's effect record (§13) |
| ADR-0148 §2–§6, §8 | Nothing: they are stated over an egress call a policy rules on, and the line makes none (§11:2) |
| ADR-0154 §2:2 | Its *§1's single route through `ToolInvoker.invoke`* limb, for the line alone (§11:3). Its other limbs bind every egress call as written |
| ADR-0154 §2:4 | Its *no configuration that grants a standing authorisation for a recipient* limb, for the line alone: the settings and the connect act authorise the one chat (§12:1). The first send is gated as every later one is |
| ADR-0154 §4:3 | For the line alone: its calls are covered by the owner's recorded acts, the connect act and the settings, rather than by a decision of the user about each call, as ADR-0247 rested a search on the configured provider |
| ADR-0154 §4:1, §4:2, §4:4 | Nothing. §13 is §4:1's ADR for the line's route. §4:2 and §4:4 are stated over egress calls; the line's chat is never chosen or set by content, and its rule is stated over the recorded place and the configured chat |
| ADR-0154 §6:2 | Applied: §12 states what the line places in a third-party service |
| ADR-0233 §9 | Nothing: it is stated over an egress call whose binding carries coverage, and the line's calls carry no binding |
| ADR-0231 §6:7 | Nothing: this ADR is the ADR its last sentence asks for |
| ADR-0306 §5:7 | Nothing: the line's messages are messages, not calls that leave the hub |
| ADR-0292 §10:1 | In the addition alone: a kind whose sensor cannot read its medium's history may declare an episode window (§10:1) |
| ADR-0292 §11:5, ADR-0293 §6:2–§6:3, §9:2 | Nothing: they are stated for a conversation, and this kind rules its own (§5:5, §6:10) |
| ADR-0292 §5:4, §6:5, §6:9, §8, §9, §10:2 | Applied: §9 |
| ADR-0321 §3:3 | Its second sentence, restated without naming a channel (§4:7). Its first sentence stands |
| ADR-0321 §4:4 | Its *in one of your conversations*: any place whose kind establishes the user as an author (§4:8) |
| ADR-0321 §4:6 | Its *who*'s *through the hub chat*: through the channel the yes came on (§4:9) |
| ADR-0321 §2:12, ADR-0307 §3:6 | Nothing: a question on the line carries no buttons and no options (§7:1) |
| ADR-0322 | Nothing: applied on the line as in the hub chat (§7) |
| ADR-0284 §2:2 | Nothing: applied. The kind's declaration states the origin per input, `outside` for an input that takes in a forward (§4:11) |
| ADR-0295 | Nothing: the line adds no stop route (§8) |

> **Normative.** This numbered draft records its replacements on the status lines and in a dated
> header note of ADR-0148, ADR-0154, ADR-0155, ADR-0292 and ADR-0321, atomically with this ADR
> under ADR-0070 and ADR-0082, preserving their ratified bodies. The replacements take effect on
> this ADR's ratification.

## Consequences

**What becomes possible.**
- You message the assistant from anywhere, and your phone's Telegram notifications tell you it
  answered. Once the timers milestone lets the assistant write first, they will also bring you
  its reminders.
- A yes on the line approves a call as a yes in the hub chat does, and a later channel declares
  how it establishes authors without touching authorizing.
- The egress seam can write: #2076 is settled for the line, and the search and forecast stay
  reads.

**What it costs.**
- Telegram holds the chat, and with it whatever the assistant wrote there (§14).
- After a forward, a remember asks and a call that leaves the hub needs you (§4, #2856).
- Messages sent while the hub is down for more than a day are lost, unnoticed (§5).
- The line has no stop of its own (§8).
- The egress corpus gains a second kind of route: a line whose approval is standing. Each
  supersession is scoped to the line, and §13 is what holds the seam's conditions on it.

**What follows.** A Telegram milestone, with acceptance scenarios, once this ADR merges (owner,
2026-10-17). Its lanes build §15's table, back to back, in that milestone.

**What it leaves open.**
- **Withholding secret-tier memories from lines another party holds.** Not taken for now (owner,
  2026-10-17). It stays a named later option.
- **Buttons as reply shortcuts**, sending a fixed typed answer when tapped (§7).
- **Groups, topics and other people in the chat**: places that nest
  ([#2826](https://github.com/leonapivato/ai-assistant/issues/2826)), and more than one person in
  a medium (ADR-0292, What stays open).
- **Voice notes**, the first follow-up. **Pictures and files**, and Markdown rendered into
  Telegram's formatting.
- **Commands inside Telegram**, such as `/stop` or `/new`. A message never becomes a command
  (ADR-0292 §12:6). Whether a Telegram command could count as a structured act belongs to the
  device session and authority.
- **Pairing**, for when someone other than the owner sets a line up.
- **Quiet hours and other rules on the assistant writing first**: the timers and proactivity
  milestone.
- **Noticing a long outage**: telling you that messages from more than a day ago may be lost.
- **The carrier line**: Telnyx or similar, RCS where the phone supports it and SMS as the
  fallback. Its sender is only claimed, and its reader takes webhooks, which brings back the
  question of a public address.
- **A spoke on a device**, such as iMessage through a Mac relay. The kind's contract is written
  so that a spoke on a device can carry it too.
- **Hosting a whole hub on a rented server**: decided later (owner, 2026-10-17).
- **A word for a spoke inside the hub**: ADR-0292's own open item, which this kind cites rather
  than settles.

## Alternatives considered

- **Telegram mirroring the hub chat.** Ruled against (owner, 2026-10-11). You would see one
  conversation everywhere, but every message would be held twice and kept in step, edits and
  deletions would not map across, many hub conversations would fold onto one linear chat, and a
  bridge would have to pose as one of your devices.
- **No places: the channel is the chat.** Ruled against. A changed account's chat would continue
  the old one's history, and every later case of more than one chat would need a redesign.
- **Pairing with a one-time code.** Deferred. It proves possession of the account at setup, but
  needs a command, a store of expiring codes and `/start` handling; a setting does the job while
  the owner is the only person setting a line up.
- **Silence after a restart, as in the hub chat.** Ruled against: Telegram has no current state
  to show *interrupted*.
- **Voice notes in the first build.** Ruled against: they follow it at once.
- **Webhooks instead of long polling.** Telegram would call the hub, which would need a public
  address it does not have.
- **Keeping waiting messages in the hub.** It gains nothing on an outage, since Telegram's 24-hour
  limit binds the same way while the hub is down, and the hub would hold message text outside
  episodes.
- **Buttons on questions**, as the proposal had them. Not taken: ADR-0321 §2:12 came after the
  walk and governs, so answers are typed (§7).
- **A per-message approval of the bytes**, ADR-0233's surface. Rejected as unusable for a chat:
  every reply would ask first.
- **The line as an egress boundary of its own**, beside the remote transports, outside the
  `tools/` seam. Not taken: it would add a second transport module and still meet ADR-0155 §1:1,
  and the owner chose the seam.
- **A Telegram library** (python-telegram-bot, aiogram). Not needed, and each brings its own HTTP
  stack.
- **Other providers.** Signal, iMessage, SMS, RCS and WhatsApp are compared on #2819.
