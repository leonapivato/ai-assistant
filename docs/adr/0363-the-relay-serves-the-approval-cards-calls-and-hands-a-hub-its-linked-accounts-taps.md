# 363. The relay serves the approval card's calls, and hands a hub its linked account's taps

- Status: Proposed
- Date: 2026-11-01
- Scope: the relay's contract with a hub (ADR-0330 §4), widened by the calls an approval card makes on the line (ADR-0361 §4): a post with buttons, its edits, a tap handed to the hub and the tap's answer. Milestone 19, "Approvals by card". The relay is the private repository's, and §6 is its lane.
- Dependency: [ADR-0330](0330-a-hubs-telegram-line-may-run-through-a-relay-on-the-box-which-serves-it-the-bot-api-for-one-linked-account-and-the-hub-trusts-it-by-a-certificate-configured-at-setup.md), whose §4 this amends; [ADR-0361](0361-approvals-are-cards-the-person-taps-and-a-yes-is-a-one-time-ticket-for-the-exact-call.md), whose §4:12 has the relay serve the card's calls; [ADR-0323](0323-a-telegram-chat-with-the-owners-bot-is-a-line-to-the-assistant-and-connecting-it-approves-what-the-line-carries.md); and [ADR-0362](0362-a-ticket-runs-the-person-models-calls-and-the-task-schedulers-and-a-cards-edit-and-a-taps-answer-need-no-claim-of-the-lines.md), whose §4 rules how the hub gates and records a card's edit and a callback's answer; all as their status lines leave them.
- Authorization: the coordinator agreed this direction on 2026-11-01, as the brief for this lane records, and assigned 0363. The coordinator ratifies it under the owner's delegation once its reviews are green (§1:1).
- **Changes no `core` contract.** The hub's side is built on `main` at `bf66b683d` by AP3 (#3573): `TelegramBotClient` has `send_with_buttons`, `edit_message` and `answer_callback`, and `HttpsTelegramBotClient` sends them to the relay's origin as to Telegram's. No member, argument, result, `Settings` field or `core/types.py` shape changes, and `PROTOCOL_VERSION` does not advance. It does change a trust boundary, the relay's contract, so both review lenses run.
- **Partially supersedes** [ADR-0330](0330-a-hubs-telegram-line-may-run-through-a-relay-on-the-box-which-serves-it-the-bot-api-for-one-linked-account-and-the-hub-trusts-it-by-a-certificate-configured-at-setup.md), in the clauses §7 names, and no clause of any other ADR.

## Context

In this document a bare section reference, such as §3:2, is to this decision's own clauses.

ADR-0361 §4:12 says that "in relayed mode the relay serves them as it serves the line's other
calls (ADR-0330 §4:16)", where *them* is posting a card, editing it and answering a button's
callback. ADR-0330 §4 says otherwise, and no record supersedes it:

- §4:1 and §4:2: the relay serves `getUpdates`, `sendMessage` and `sendChatAction`, and "no
  method other than those three".
- §4:3: "Every update the relay hands a hub is a `message` update".
- §4:10, §4:13 and §4:15 name `sendMessage` and `sendChatAction` alone.

The relay on the private repository's `main` (`06f5226`) holds to that. It accepts
`sendMessage` with `chat_id` and `text` and no other member, answers `404` to any other
method, and asks Telegram for `["message"]` alone. So on a relayed line a card's post is
refused, and the card is *not done*: the request waits on the hub-page panel (ADR-0361 §4:6).
Edits and callback answers are refused, which changes nothing in the store. That is safe, and
it is what a relayed line does until §6's lane lands. The owner's hub reaches Telegram
directly, so this blocks no deploy of it.

What the hub sends, from AP3's code (`tools/egress.py`):

| Method | What the hub sends | What it reads back |
| --- | --- | --- |
| `getUpdates` | `allowed_updates` `["message", "callback_query"]` | a `callback_query`'s `id`, `from.id`, `from.is_bot`, `message.message_id`, `message.chat.id`, `message.chat.type` and `data` |
| `sendMessage` | `chat_id`, `text`, and for a card `reply_markup`: one row of 1–8 buttons, each a `text` of at most 64 characters and a `callback_data` of at most 64 bytes | `result.message_id` |
| `editMessageText` | `chat_id`, `message_id`, `text`, and `reply_markup` of the same shape or `{"inline_keyboard": []}` | `result` |
| `answerCallbackQuery` | `callback_query_id`, and a `text` of at most 200 characters | `result` |

`answerCallbackQuery` names no chat. The callback query's id is the only thing in it that ties
it to anyone.

## Decision

We will have the relay serve the card's two further methods and `sendMessage`'s one-row
keyboard, under the checks ADR-0330 §4 already makes of a send, and hand a hub the linked
account's taps on its own chat's messages as Telegram delivered them. An answer to a tap is
accepted only for a tap the relay handed that hub and the hub has not yet confirmed.

### 1. Status and delivery

> **Normative.** This document remains `Proposed` until the adversarial and architecture
> reviews `CONTRIBUTING.md` → "Finishing an ADR PR" requires have returned green on one tree
> and the coordinator, under the owner's delegation, ratifies it. An assigned number or a
> green review alone does not change its status.

> **Normative.** No lane implements this decision before it merges `Accepted` (ADR-0015 §5).
> Its one lane is §6's.

### 2. The methods

> **Normative.** The relay serves a hub `getUpdates`, `sendMessage`, `sendChatAction`,
> `editMessageText` and `answerCallbackQuery`, at the request targets and in the shapes
> ADR-0330 §4:1 states, and no other method.

> **Normative.** A `sendMessage` may carry a `reply_markup`. Where it does, the markup is an
> object whose one member is `inline_keyboard`, holding exactly one row of 1–8 buttons. Each
> button is an object whose only members are `text`, a string of 1–64 characters, and
> `callback_data`, a string of 1–64 bytes in UTF-8.

> **Normative.** An `editMessageText` carries `chat_id`, `message_id` and `text`, checked as
> `sendMessage`'s `chat_id` and `text` are, and may carry a `reply_markup` of §2:2's shape or
> `{"inline_keyboard": []}`. It carries no other member.

> **Normative.** An `answerCallbackQuery` carries `callback_query_id`, a string, and may carry
> `text`, a string of at most 200 characters. It carries no other member.

> **Normative.** The relay refuses, with a client error before anything reaches Telegram, a
> request carrying a member, a button or a markup that §2:2–§2:4 do not admit.

The keyboard is held to the one shape the hub sends because the Bot API's other buttons carry
other authority. A `login_url` button signs the tapper in to a website with their Telegram
account, a `url` or `web_app` button opens a page, and a reply keyboard can send the person's
phone number or location in one tap. `answerCallbackQuery`'s `url` opens a link for the
tapper. None is the line's.

### 3. The checks every send already has

> **Normative.** ADR-0330 §4:10–§4:13 bind `editMessageText` and `answerCallbackQuery` as they
> bind `sendMessage`: `ok: true` only with Telegram's own answer, a refusal only for a call not
> performed, no refusal for a call passed on and unanswered, and no call passed on repeated.

> **Normative.** The relay refuses an `editMessageText` whose `chat_id` is not the hub's
> linked account's private chat with the bot, answering a client error before anything reaches
> Telegram, as ADR-0330 §4:15 refuses a `sendMessage`.

> **Normative.** The relay counts each `editMessageText` and `answerCallbackQuery` it would
> pass on against the limits it holds a hub's sends to, and answers one over them as ADR-0330
> §4's table answers a send over the relay's own rate limit.

> **Normative.** ADR-0330 §10:1 binds the two methods and a card's `reply_markup`: the relay
> keeps no copy of an edit's text, a button's label or data, or an answer's text after the
> call that carries it ends, in any store, log or diagnostic.

The relay's checks add to the hub's own and replace none. The hub is the same client whatever
it reaches (ADR-0330 §4:16), so the gate it holds before a card's edit or a callback's answer,
and how it records each, are ADR-0362 §4:1–§4:5's, in relayed mode as in direct.

### 4. Taps

> **Normative.** The relay asks Telegram for `message` and `callback_query` updates, and for no
> other kind.

> **Normative.** The relay hands a hub a `callback_query` update only where its sender is that
> hub's linked account and not a bot, and its `message` is in the linked account's private chat
> with the bot. That is how ADR-0330 §5:2 reads for a tap: its sender is its `from`, and its
> chat is its message's chat.

> **Normative.** Every member of a `callback_query` the hub reads is unaltered: its id, its
> sender, its message's id and chat, and its data. The relay fabricates, alters and reorders
> none, as ADR-0330 §4:3 rules for a `message` update.

> **Normative.** Any other `callback_query` is withheld from every hub, as an update from an
> account that is not linked is. The relay does not answer it, and keeps no copy of it.

> **Normative.** ADR-0330 §4:4–§4:8 bind a `callback_query` update as they bind a `message`
> update: its id, its order, its confirmation by the hub's offset and its handing again.

A hub reads an update it cannot read as a message or a tap as not input (ADR-0323 §5:1), and
confirms it once seen (ADR-0323 §5:6), so the relay need not filter by a poll's
`allowed_updates`.

### 5. Which answers the relay accepts

> **Normative.** The relay accepts an `answerCallbackQuery` on a hub's credential only where its
> `callback_query_id` is the id of a `callback_query` update the relay has handed that hub and
> the hub has not yet confirmed. Any other it refuses with a client error before anything
> reaches Telegram.

> **Normative.** The relay keeps a handed callback's id no longer than it keeps the update:
> once the hub confirms the update (ADR-0330 §10:2), or the person unlinks (ADR-0330 §11:3),
> an answer naming it is refused.

Why the handed id, and why only until confirmation:
- **The id is the only tie.** The call names no chat. Without the check, a hub holding any
  callback id could show text to another hub's person.
- **The hub answers before it confirms.** Its reader deals with a poll's updates, the tap's
  answer among them, before its next poll sends the offset that confirms them
  (`orchestration/telegram.py`, `_once`). So the window covers every answer the hub makes,
  its retries included.
- **Nothing outlives the update.** A fixed window would keep part of an update after the hub
  confirmed it, which ADR-0330 §10:2 keeps to nothing. Ending with the update keeps it.
- **A late answer loses only its text.** The tap is carried out by the hub's store step
  before its answer (ADR-0361 §4:9). An answer refused leaves the tapper without the short
  text, and changes nothing.

What each new answer becomes in the hub, extending ADR-0330 §4's table by the client's
existing rules:

| What happened at the relay | What it answers | `TelegramFailure` in the hub |
| --- | --- | --- |
| A markup, button or member §2 does not admit | a client error | `REFUSED`; a card's post is then *not done*, and the request waits on the panel |
| An edit naming another chat | a client error | `REFUSED`, after the hub's own `OTHER_CHAT` check |
| An answer naming an id not handed to this hub, or confirmed | a client error | `REFUSED`; the tap already stands |
| An edit Telegram refused, "message is not modified" among them | Telegram's own refusal | `REFUSED`, as Telegram said |

Every other row of ADR-0330 §4's table holds for the two methods as it does for a send.

### 6. The lane

> **Normative.** One lane in the private repository builds this decision: the relay's code,
> its tests, and `docs/design/telegram-relay.md`. It owes no lane in this repository: what
> the hub owes for a card's edit and a callback's answer is ADR-0362 §4:1–§4:5's, in direct
> and relayed mode alike.

> **Normative.** That lane's tests cover, against a fake Telegram: each refusal of §2:5, §3:2
> and §5:1 made before anything reaches Telegram; an answer refused once its update is
> confirmed; a tap from another account, or on a message in another chat, withheld and
> unanswered; and a tap handed with the members §4:3 names unaltered.

> **Normative.** This decision decides nothing of the relay's internals beyond what §2–§5
> require of it, as ADR-0330 §13:1 decides nothing of them beyond its own list.

The relay's redeploy on the box is the coordinator's, held by milestone 19.

### 7. Relationship to earlier decisions

Superseded in part. Every clause the middle column does not name stands:

| Earlier decision | What it replaces | By |
| --- | --- | --- |
| ADR-0330 | §4:1 and §4:2, in the addition alone: `editMessageText` and `answerCallbackQuery` are served too; §4:3, in the addition alone: a `callback_query` update from the linked account, in its chat, is handed too, unaltered; §4:10, §4:13 and §4:15, in the addition alone: they bind the two methods, and §4:15's chat check binds `editMessageText` | §2, §3, §4 |

Read through and not superseded:

| Earlier decision | What changes |
| --- | --- |
| ADR-0330 §5:2, §6:1 | Nothing: a tap's sender and chat are read as §4:2 says, and an answer is tied to the hub by §5:1 |
| ADR-0330 §9 | Nothing: its rows defer to ADR-0323 §13 as ADR-0362 §4 leaves it, and row 8's relay check gains §3:2 and §5:1 |
| ADR-0330 §10:1, §10:2 | Nothing: §3:4 and §5:2 keep both |
| ADR-0361 §4:12 | Nothing: this decision is what it relied on |

> **Normative.** This numbered draft records its replacements on ADR-0330's status line and in
> a dated header note there, atomically with this ADR under ADR-0070 and ADR-0082, preserving
> its ratified body. The replacements take effect on this ADR's ratification.

## Consequences

- A relayed line's card works as a direct one's, once §6's lane lands and the relay is
  redeployed. Until then a relayed card is *not done*, and the request waits on the panel.
- The relay serves two more methods and one more kind of update, each held to the one shape
  the hub sends.
- A hub can answer only its own person's taps, and only while it holds them unconfirmed.
- The relay keeps nothing new: a tap's id goes with its update.

## Alternatives considered

- **Remember handed ids for a fixed time.** Rejected: it keeps part of an update past its
  confirmation, which ADR-0330 §10:2 rules out, and covers no answer the hub makes.
- **Check `answerCallbackQuery` by nothing but the credential.** Rejected: the call names no
  chat, so one hub could answer another's person.
- **Accept any `reply_markup` the Bot API documents.** Rejected (§2): its other buttons sign
  people in, open pages and change their keyboard.
- **Filter taps by each poll's `allowed_updates`.** Rejected: it adds a per-poll filter to the
  relay's queue, and a hub already reads an update it did not ask for as no input.
