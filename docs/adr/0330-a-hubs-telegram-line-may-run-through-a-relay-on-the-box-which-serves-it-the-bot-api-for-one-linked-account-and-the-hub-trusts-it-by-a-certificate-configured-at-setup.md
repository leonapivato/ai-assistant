# 330. A hub's Telegram line may run through a relay on the box, which serves it the Bot API for one linked account, and the hub trusts it by a certificate configured at setup

- Status: Partially superseded by ADR-0332 (§4:3's members a relay hands unaltered, in the addition alone: a message's `entities`) and ADR-0363 (§4:1, §4:2, §4:3, §4:10, §4:13 and §4:15, each in the addition alone: the approval card's calls and the linked account's taps)
- Date: 2026-10-18
- Scope: the hub's side of the shared Telegram bot: what a hub requires of a relay that holds the bot, and how the line changes when it reaches one. Tracker: [#3140](https://github.com/leonapivato/ai-assistant/issues/3140), acceptance [#3133](https://github.com/leonapivato/ai-assistant/issues/3133), the client-side implementation [#3141](https://github.com/leonapivato/ai-assistant/issues/3141). The relay itself and the account-linking flow are the private repository's.
- Dependency: ADR-0323, ADR-0327, ADR-0191, ADR-0231, ADR-0125 and ADR-0154, as their status lines leave them.
- Authorization: the owner's ruling of 2026-10-18 on #879 ([the ruling](https://github.com/leonapivato/ai-assistant/issues/879#issuecomment-6252766646)): each hosted person has "one hub per person, reached through one shared Telegram bot and the web. The bot is linked to each person's account", and the router is built now, in milestone 13. The owner closed the Telegram line's acceptance on 2026-10-19 ([#3118](https://github.com/leonapivato/ai-assistant/issues/3118#issuecomment-6258451363)). What remains is technical, and this ADR settles it. The dispatcher assigned 0330 for Hosted setup C1.
- **Changes a `core` contract, so it is a contract-surface decision.** It restates the `TelegramBotClient` contract's fixed-origin rule and its credential rule for a relayed line, and adds two `Settings` fields (§12). No member, argument, result or `core/types.py` shape changes, and `PROTOCOL_VERSION` does not advance (§12:5).
- **Partially supersedes** [ADR-0323](0323-a-telegram-chat-with-the-owners-bot-is-a-line-to-the-assistant-and-connecting-it-approves-what-the-line-carries.md), for a line in relayed mode alone and in the scopes §14 lists, and no clause of any other ADR.
- Partially superseded: 2026-10-21 by ADR-0332 — §4:3, in the addition alone: a message's `entities` are among the members the hub reads that a relay hands unaltered, so the line's `/stop` reads alike in direct and relayed mode (ADR-0332 §7:9, §7:10). Every other clause stands. This replacement takes effect on ratification of ADR-0332. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.
- Partially superseded: 2026-11-01 by [ADR-0363](0363-the-relay-serves-the-approval-cards-calls-and-hands-a-hub-its-linked-accounts-taps.md) — §4:1 and §4:2, in the addition alone: the relay also serves `editMessageText` and `answerCallbackQuery`, and no other method (ADR-0363 §2:1). §4:3, in the addition alone: it also hands a hub a `callback_query` update from the linked account on a message in its private chat with the bot, with the members the hub reads unaltered (ADR-0363 §4:2–§4:3). §4:10, §4:13 and §4:15, in the addition alone: they bind the two methods, and the relay refuses an `editMessageText` naming any other chat (ADR-0363 §3:1–§3:2). Every other clause stands. This replacement takes effect on ratification of ADR-0363. This reciprocal header record accompanies the numbered draft under ADR-0070 and ADR-0082; prior supersessions and the ratified body below are preserved.

## Context

### The question

The owner's ruling puts one Telegram bot in front of every hosted hub. Each person links their
own Telegram account to it, and messages from that account reach only their own hub. ADR-0323
built the line for a bot of the hub's own: the hub holds the bot's token and calls Telegram
directly. With one bot shared by everyone, no hub may hold the bot's token, because whoever
holds it reads every person's messages and sends to any of them as the bot. So the bot needs one
holder, the **relay**, a program on the operator's box, and each hub reaches the relay instead
of Telegram.

This ADR decides the hub's side: what a hub requires of a relay, and what changes in the hub's
line when it uses one. How the relay is built, how it receives updates from Telegram, and how a
person links their account from the signed-in page are the private repository's.

### What is built on `main`

- **The line's client** is the `TelegramBotClient` contract in `core/protocols.py`, implemented
  once, by `HttpsTelegramBotClient` in `tools/egress.py`. It calls three Bot API methods and no
  others, named there as `_GET_UPDATES`, `_SEND_MESSAGE` and `_SEND_CHAT_ACTION`: `getUpdates`,
  `sendMessage` and `sendChatAction`. The reader and the writer in `orchestration/telegram.py`
  hold the contract and never the class, and `app/composition.py` builds the client only while
  the line is configured.
- **The origin is fixed in code.** `TELEGRAM_BOT_API_ORIGIN` is `https://api.telegram.org`, and
  the contract's rule 5 says so: "One request, to the one origin `https://api.telegram.org`,
  fixed in code". ADR-0323 §11:5 rules it.
- **The token is a path segment.** The client binds the token into `/bot<token>/<method>` after
  the credential read, and refuses a token spelled outside letters, digits, `:`, `_` and `-`
  (`_TELEGRAM_TOKEN_CHARACTERS`).
- **What an answer means.** `_answer_of` reads a JSON object with a boolean `ok`. `ok: true` on
  a `200` with a `result` is done. `ok: false` with an `error_code` of `429` is
  `TelegramFailure.RATE_LIMITED`, with any other client error it is `REFUSED`, and anything else
  is `UNKNOWN`. A channel that could not be opened is `NOT_WRITTEN`. `TelegramFailure.retryable`
  is true for `NOT_WRITTEN` and `RATE_LIMITED` alone.
- **The seam has no cleartext form.** `TransportEndpoint` in `core/types.py` has "no third value
  and in particular no cleartext one", `parse_https_origin` in `tools/egress.py` always returns
  `implicit_tls`, and `HttpsExchange.post_json` writes nothing before the channel reads secure.
- **The HTTPS canonicaliser refuses IP literals.** ADR-0231 §8:5 and §8:6 refuse a host that is
  an IP literal in any notation, and `_check_https_host` in `tools/destinations.py` holds that.
  A single-label host name, such as one a container network resolves, canonicalises.
- **TLS is verified against the endpoint's host.** ADR-0191 §4:2 requires every implementation
  that establishes TLS to verify the peer's certificate chain and its hostname, and forbids
  either Protocol exposing a caller-supplied trust configuration. `_tls_context` in
  `tools/egress.py` builds today's context on the system's trust store.

### What the corpus says that this has to move

- **ADR-0323 §11:5**: "The line reaches one origin, `https://api.telegram.org`, fixed in code and
  never configured". A relayed line reaches the relay.
- **ADR-0323 §4:3**: "the reader compares the sender id Telegram reports against the setting,
  and adds no authentication of its own". With a relay in the path, the hub hears Telegram's
  report from the relay. So the hub must authenticate the relay, and the clause must say how
  Telegram's report reaches the reader.
- **ADR-0323 §3:1, §11:4, §11:8 and §11:9** speak of the bot's token. A relayed hub holds no
  bot token. It holds a credential of its own, which the same rules must protect.
- **ADR-0323 §12:1**: the connect act and the two settings are the approval. Under #879's
  terms, "The operator never performs an act that carries the person's authority: no approval,
  no grant". For a hosted person, the operator performs setup at the person's request, so the
  approval has to rest on an act of the person's own.
- **ADR-0323 §14** states the line's privacy costs, and a relay adds one: it sees everything.

### Why the hop to the relay is TLS, when the hosted listener is plain HTTP

ADR-0327 §5:6 lets the gateway's hosted listener speak plain HTTP to the edge, on the box. Its
reasoning was this: the gateway accepts connections and fetches nothing (ADR-0327 §3:4); it checks a
signature on every request; and an assertion lives for at most five minutes, so a replay is
bounded and reaches only the operator. None of that carries over to the relay.

- **The hub dials out.** An outbound connection is ADR-0191's injected capability, whose endpoint
  type has no cleartext form. A plain-HTTP relay would need a new `TransportEndpoint` mode and a
  new form in the seam. That is a `core/types.py` change, reversing a ratified "no third value".
- **The credential is standing.** It is not a sixty-second assertion. Whoever reads it once can
  read the person's messages and write to them as the bot until it is revoked.
- **What must be authenticated is the response.** The hub takes a poll's answer as Telegram's
  word about who wrote a message. A message the hub reads as the person's carries their
  authority, and can approve a call that leaves the hub (ADR-0323 §4:6, §4:7). Signing responses
  would need a scheme of our own that binds each response to its request. TLS does this already,
  and so do the hub's other channels.
- **The path is the box's internal network.** In ADR-0327 it was loopback. Other people's hub
  containers share that network, not just the operator.

Anchoring the hub's TLS on a certificate the operator configures at setup gives one standard
mechanism with all three properties: authentication of the relay, integrity and freshness of what
it returns, and confidentiality for the credential and the messages on the hop. It is the same
check ADR-0327 makes with a configured Ed25519 key, moved into the channel the hub already opens.

## Decision

We will let a hub's Telegram line run in one of two modes. **Direct** is ADR-0323's line,
unchanged and the default. **Relayed** reaches a relay on the box, configured at setup, which
holds the shared bot and serves the hub the Bot API's three calls over the updates of the one
Telegram account the person linked. The relay knows the hub by a per-hub credential that the hub
keeps in its keyring and sends inside TLS. The hub knows the relay by a certificate configured at
setup, and trusts nothing the relay returns on any other channel. The reader still compares every
sender with the hub's own setting.

### 1. Status and delivery

> **Normative.** This document remains `Proposed` until the reviews `CONTRIBUTING.md` →
> "Finishing an ADR PR" requires have returned green on one tree and the owner's authorization
> to ratify stands. An assigned number or a green review alone does not change its status.

> **Normative.** The hub's relayed mode is built by its own lane after this decision merges
> `Accepted`, as #3141 tracks, and by no lane before. That lane changes the `TelegramBotClient`
> contract and its conformance suite as §12 states, together with the client, the settings and
> the composition root.

### 2. Terms

> **Normative.** The **relay** is a program on the operator's box. It holds the shared bot's
> token and receives the bot's updates from Telegram. It serves each hub that uses it the Bot
> API's calls of §4, over that hub's linked account alone. It is outside this repository. This
> decision binds what a hub requires of it and accepts from it, never how it is built.

> **Normative.** A hub's **linked account** is the one Telegram account the relay routes to that
> hub. The person links it from their signed-in page, through the relay's flow.

> **Normative.** A line is in **direct mode** when it reaches its own bot at
> `https://api.telegram.org` with the bot's token, as ADR-0323 builds it. It is in **relayed
> mode** when it reaches the relay with the hub's relay credential.

> **Normative.** A hub's **relay credential** is the value the relay mints for that one hub,
> by which the relay knows the hub (§6).

### 3. Two modes, configured per hub

> **Normative.** A line is in relayed mode exactly when `telegram_relay_origin` is set. Unset,
> which is the default, is direct mode, and a line in direct mode is ADR-0323's line, with every
> clause of it binding as written and none of this decision's relayed-mode clauses reaching it.

> **Normative.** A line in relayed mode makes every Bot API call to the relay's origin and none
> to `https://api.telegram.org`. A line in direct mode makes none to a relay.

> **Normative.** A line's mode is fixed when its client is built from the settings loaded at
> start, and changes only with the settings, at a restart. No call, request or answer selects or
> changes it.

> **Normative.** `telegram_relay_origin` is an HTTPS origin. The composition root puts it through
> the seam's canonicaliser (ADR-0231 §8) before it builds the line's client, and a value that does
> not canonicalise refuses the hub's start. Its canonical form is the one origin a relayed line
> reaches, so it names a host, never an IP literal, and carries no path.

> **Normative.** `Settings` checks `telegram_relay_origin` at load only as text, and holds no copy
> of the canonicaliser's rules: ADR-0231 §8:7 keeps those at the seam, in `ai_assistant.tools`.

> **Normative.** `telegram_relay_origin` is refused at settings load while the line is not
> configured, that is, while ADR-0323 §3:2's two settings are unset.

> **Normative.** `telegram_relay_certificates` is the set of certificates a relayed line trusts
> for the relay, and no others (§7). It is refused at settings load when it is empty while
> `telegram_relay_origin` is set, and when it is non-empty while that origin is unset. Each is
> something the operator wrote about a relay, so a value no reading makes true is refused rather
> than ignored (ADR-0327 §6:13's reason).

> **Normative.** A certificate in `telegram_relay_certificates` that the relayed transport cannot
> load as a trust anchor refuses the hub's start, at the composition root, before any call.

> **Normative.** The relay's certificates are Tier 2 configuration, written at the hub by the
> operator at setup. Rotating them is an act at the hub: the operator adds the new certificate,
> restarts the hub, and removes the old one once the relay no longer presents it. No request on
> any surface adds to, removes from or replaces the set.

### 4. The relay serves the Bot API faithfully

"Faithfully" means that the hub's client, reader, intake record and writer cannot tell the relay
from Telegram, except by the origin and the trust anchor. So none of them changes for relayed
mode, and every ADR-0323 rule they keep holds as it does against Telegram.

> **Normative.** The relay serves a hub `getUpdates`, `sendMessage` and `sendChatAction` at the
> Bot API's own request targets, `/bot<credential>/<method>`, with the hub's relay credential in
> the token's place. It takes the Bot API's JSON request bodies for those methods and answers in
> the Bot API's response shape: a JSON object with a boolean `ok` and, when it is true, the
> `result` the Bot API documents for that method.

> **Normative.** The relay serves a hub no method other than those three. No request on a hub's
> credential sets a webhook, changes the bot's commands or profile, logs the bot out, or acts on
> any other chat.

> **Normative.** Every update the relay hands a hub is a `message` update, as Telegram delivered
> it to the bot. Every member the hub reads is unaltered: the message, its sender, its chat, its
> date, its text, its forward origin and the message it replies to. The relay fabricates,
> alters and reorders none.

> **Normative.** The relay may withhold an update from a hub, such as one its own linking flow
> consumes. A withheld update reaches no hub.

> **Normative.** An update the relay hands a hub for the first time has an id greater than every
> update id it handed that hub before. An update handed again, because the hub has not confirmed
> it, keeps its id and is handed unaltered. No id is ever handed with a different update.

> **Normative.** Every poll's updates are in ascending update id.

> **Normative.** A hub's poll offset confirms that hub's updates below it and no other hub's. An
> update the hub has not confirmed is handed again on the hub's next poll, until the hub
> confirms it.

> **Normative.** The relay holds a poll open no longer than the wait the poll asked for, so that
> the bound ADR-0323 §11:10 gives a poll covers it.

> **Normative.** Message ids, chat ids and user ids are Telegram's own. The chat a hub's line
> writes to is the linked account's private chat with the bot, whose id is the linked account's
> id, and a send's result carries the message id Telegram returned.

> **Normative.** The relay answers `sendMessage` and `sendChatAction` with `ok: true` only with
> Telegram's own answer to that call, after Telegram accepted it. It accepts no send into a queue
> of its own, and it answers none early.

> **Normative.** The relay answers a hub with a Bot API refusal, meaning `ok: false` with an
> `error_code` in the client-error class (`429` among them), only for a request that was not
> performed. That is either a request it did not pass on to Telegram, or one Telegram itself
> refused. Telegram's refusal is passed on unaltered, `retry_after` included.

> **Normative.** A request the relay passed on to Telegram and got no answer for is answered
> with no Bot API refusal. The relay answers with a server error, or closes the connection, so
> that the hub records it as *unknown* (ADR-0323 §6:4).

> **Normative.** The relay never repeats a `sendMessage` or a `sendChatAction` it passed on to
> Telegram. Whether to send again is the hub's, under ADR-0323 §6:3.

> **Normative.** On a credential it does not know, the relay answers `ok: false` with
> `error_code` `401`, as Telegram answers an unknown token, and serves nothing and sends nothing
> on it.

> **Normative.** The relay refuses a `sendMessage` or a `sendChatAction` that names any chat but
> the hub's linked account's private chat with the bot, answering a client error before anything
> reaches Telegram.

What each answer becomes in the hub, by the client's existing rules:

| What happened at the relay | What it answers | `TelegramFailure` in the hub |
| --- | --- | --- |
| Telegram accepted it | Telegram's `ok: true` and `result` | done |
| The relay's own rate limit, before passing it on | `429`, with `retry_after` | `RATE_LIMITED`, retried |
| Telegram refused it | Telegram's own refusal | `RATE_LIMITED` or `REFUSED`, as Telegram said |
| An unknown credential | `401` | `REFUSED` |
| Another chat | a client error | `REFUSED`, after the hub's own `OTHER_CHAT` check (§5:3) |
| Passed on, no answer from Telegram | a server error, or no answer | `UNKNOWN`, never retried |
| The relay's certificate does not verify | nothing; no byte was written | `NOT_WRITTEN` (§7:4) |

> **Normative.** In relayed mode the relay stands in Telegram's place in ADR-0323's clauses that
> name Telegram as what the line's calls reach. Those are what the hub calls out to (§2:7), where
> a message waits (§5:5), what an update is confirmed to (§5:6), what the reader asks nothing of
> while an activation runs (§5:7), what a poll asks to hold it open (§11:10), and what the line's
> first call reaches (§13:1). Each binds unchanged otherwise.

Where ADR-0323 names Telegram as the source of a value, such as the sender id, a message's time,
a forward's original sender or a sent message's id, the value is still Telegram's: §4:3 and §4:9
of this decision make the relay hand it on unaltered.

### 5. Who establishes the sender

ADR-0323 §4:3 rests the user's identity on Telegram's authentication of its own users. In relayed
mode that still holds. Telegram authenticates the person to Telegram. The relay receives
Telegram's report and routes it by the linked account. The reader still compares the sender with
the hub's own setting. What the hub adds is an authentication of the **relay**, which is the
channel Telegram's report arrives on. It adds no authentication of the **user**.

> **Normative.** In relayed mode the line establishes the user by Telegram's own authentication
> of its users, as the relay hands on Telegram's report. The reader compares the sender id the
> update carries against `telegram_user_id`, and adds no authentication of the user of its own.
> "How sure" is established or claimed, never another value.

> **Normative.** The relay routes to a hub only updates from that hub's linked account, in its
> private chat with the bot.

> **Normative.** In relayed mode every rule of ADR-0323 §4 and §5 binds the reader unchanged,
> and the client's refusal of another chat (ADR-0323 §6:1) binds the client unchanged. An update
> whose sender is not `telegram_user_id`, or that is not in its private chat with the bot, is
> not input, whoever handed it on.

> **Normative.** In relayed mode an update is Telegram's report only when it arrived on a channel
> that §7's check admitted. Nothing that arrived on any other channel is read.

The two checks fail safe when they disagree. If the relay's linked account is not the hub's
`telegram_user_id`, no update is input, and the relay refuses every send. The line carries
nothing until setup makes them agree.

What the reader's check does and does not protect, plainly:
- **It protects** against a relay that misroutes. Another person's message, handed to this hub,
  is not this hub's user's and starts nothing. The other person's privacy, though, rested on the
  relay, and that is already lost.
- **It does not protect** against a relay that lies. A relay can fabricate an update "from" the
  linked account, and the hub will take it as the person's own, established, with their
  authority. Nothing in the Bot API lets the hub check Telegram's word past the relay. The relay
  is trusted as the box is (§10).

### 6. The relay authenticates the hub

> **Normative.** The relay authenticates every request by the hub's relay credential before it
> serves any update or sends anything as the bot. On one hub's credential it serves only that
> hub's linked account's updates, and sends only to that account's private chat with the bot.

> **Normative.** The relay mints each hub's credential distinct from every other hub's, with at
> least 128 bits drawn from a cryptographically secure source. It is spelled only in ASCII
> letters, digits, `_` and `-`: the characters a bot token's path segment admits, without the
> `:` that every Bot API token carries.

> **Normative.** In relayed mode the client refuses a credential containing `:` as
> `TelegramFailure.UNAVAILABLE`, before any byte is written, so that a bot token in the hub's
> keyring never reaches a relay.

> **Normative.** The relay credential is the credential of the connection `telegram_connection`
> names. It is connected with `assistant connect`, kept in the OS keyring under the reference the
> hub mints (ADR-0125, ADR-0149, ADR-0151), and entered only where ADR-0177 lets a credential be
> entered. It is never in `Settings`, the environment or a file (ADR-0125 §8:7).

> **Normative.** In relayed mode, ADR-0323 §11:4's rules for reading the bot's token bind the
> relay credential. It is read inside `ai_assistant.tools.egress`, through the
> `INTEGRATION`-scoped `Secrets` face, only after the call's record has been claimed and its
> checks have passed. It is read once per call, with the connection record read before it and
> again before any byte is sent.

> **Normative.** The relay credential is Tier 0 (ADR-0004 §1). ADR-0323 §11:8 and §11:9 bind it
> as they bind the bot's token: the seam binds it into the request target itself, and nothing
> that records a target carries it or any part of it.

> **Normative.** A relayed line's connection is a connection of its own. The setup connects the
> relay credential as a new connection. It never reprovisions a connection that held a bot token
> with a relay credential, nor the reverse.

So moving a line between modes is a new connection, and with it a new channel, a new place and
an empty intake record, as a new bot is under ADR-0323 §2:3. The shared bot's message ids and
update ids are not the old bot's, and an intake record or a reply link carried across would read
one bot's ids as another's. Re-minting a relay credential is a reprovisioning of the relayed
line's own connection, and moves nothing. Disconnecting removes the credential, as ADR-0323 §3:6
removes the token.

> **Normative.** No hub holds the shared bot's token: no setting, connection or keyring entry of
> a hub carries it.

### 7. The hub authenticates the relay

> **Normative.** In relayed mode the client opens every channel to the relay under TLS. It
> verifies the relay's certificate chain against the certificates in
> `telegram_relay_certificates` and against no other trust anchor, the system's certificate
> authorities included, and verifies the hostname against the origin's host.

> **Normative.** No byte of a relayed request, the credential included, is written before that
> verification has passed, as `HttpsExchange` writes nothing before its channel reads secure.

> **Normative.** The relayed line's trust anchors are fixed when its transport is built, by the
> composition root, from `telegram_relay_certificates`. No member of `OutboundTransport` or
> `ByteChannel` supplies or changes them, and no holder of the transport can.

> **Normative.** A relay whose certificate does not verify is a channel that could not be
> opened: the call is `TelegramFailure.NOT_WRITTEN`, and nothing was written.

> **Normative.** The relay presents a certificate that chains to one of the hub's configured
> certificates and names the origin's host.

ADR-0191 §4:2 is kept, not superseded. The relayed transport verifies the peer's chain and its
hostname against the endpoint it was handed. Neither Protocol gains a verification-disabling
option, a trust parameter or a second host. The anchors are the transport's own, set by the
composition root from Tier 2 configuration, just as the system store is today's transport's own.

### 8. Reachability

> **Normative.** The relay listens only on the box's loopback and on addresses of the box's own
> internal networks. No other machine, no overlay and no public network reaches it. This is part
> of the box's posture, beside ADR-0327 §4:6.

> **Normative.** The setup makes the relay origin's host resolve, inside the hub's network
> namespace, only to the relay on the box. For a hub in a container, setting that up is the
> container setup's obligation, and #3142's lane holds it.

The hub cannot check where a name resolves, and does not need to for the relay's authentication
(§7). A name that resolved elsewhere would reach a peer without the relay's key. The handshake
would fail, and nothing of the request would be written. Where the name resolves is a posture,
like the box's firewall, and not what the line's security rests on.

> **Normative.** The line never reaches the relay in cleartext. No lane adds a cleartext mode to
> `TransportEndpoint`, or a cleartext form to the seam, for it.

> **Normative.** The hop to the relay is opened through the injected `OutboundTransport`, as the
> call to Telegram is. That holds even where the relay is on the hub's own loopback. No lane
> treats it as a loopback or local connection outside the capability under ADR-0191 §5:4.

### 9. The egress classification

The hop to the relay is **ADR-0323 §11's route through the designated `tools/` seam, with a new
destination**, and not a new boundary. ADR-0327's hop needed a fifth boundary because its
listener half was in the gateway, outside the seam. Here the same client makes the same three
calls, from the same module, through the same injected transport. What changes is where they go.

What crosses it is what crosses ADR-0323's route, plus one thing:
- **The three calls.**
- **The relay credential**, in the token's place.
- **The person's messages**, coming in.
- **The assistant's messages and typing indicators**, going out.
- **A poll's offset.**

The three kinds of content ADR-0323 §12 admits for the one chat reach the relay on the box first,
and through it Telegram.

> **Normative.** Every relayed call is made in `ai_assistant.tools.egress` and in no other
> module, by ADR-0323 §11's route. This decision designates no new boundary and adds no member to
> ADR-0174 §1:1's enumeration as ADR-0327 §3:1 leaves it.

> **Normative.** On the relayed route, ADR-0017 §3's conditions hold as the table below states,
> each row in code before a relayed line's first call reaches the relay. The lane that builds
> relayed mode attests each row in its change.

| # | Condition | How it holds on the relayed route |
| --- | --- | --- |
| 1 | A named seam and an import-linter contract | As ADR-0323 §13: the client is in `ai_assistant.tools.egress` (§9:1) |
| 2 | Per-call gating before transmission | As ADR-0323 §13 |
| 3 | Recipient authorisation traced to a user act | The one chat is the person's linked account. The person's link act is the relay's record, and the hub's setup carries it out (§11:1) |
| 4 | Credential access gated | The relay credential is read only inside the seam, after the gates, with the record re-read before sending (§6:5) |
| 5 | Transport pinned, no redirect | One origin, configured and canonicalised. TLS is verified against the configured certificates alone before any write, and no redirect is followed (§3:4, §7) |
| 6 | The payload bound before transmission, described after | As ADR-0323 §13 |
| 7 | A named approver able to refuse | The person, by unlinking at the relay, and the owner's setup, by disconnecting or unsetting (§11:3) |
| 8 | What is transmitted is bound to what was authorised | As ADR-0323 §13. The relay refuses every other chat as well (§4:15) |
| 9 | Multi-recipient calls as one set | As ADR-0323 §13: one recipient |
| 10 | Destinations canonicalised | The relay's origin is canonicalised by the seam's canonicaliser (ADR-0231 §8) before the client is built, and compared exactly. The chat id is compared for equality with the setting |
| 11 | Resolving a name is gated or forbidden | As ADR-0323 §13: the line resolves no username |
| 12 | An attempt identifier and an explicit outcome | As ADR-0323 §13. A relay's answers keep the three outcomes apart (§4:11–§4:12) |
| 13 | Payload classification settled | As ADR-0323 §12, for the one chat, through the relay |
| 14 | Failure paths tested | §12:6 |

### 10. What the relay sees and keeps

Plainly, in #879's terms (the operator's custody, plain storage, trust by relationship):

- **The relay reads everything on the line.** TLS ends at the relay. Every message every linked
  person sends to the bot, and every message every hub writes back, passes through it in the
  clear on the operator's box. Telegram then sees it too, as ADR-0323 §14 says.
- **The relay holds the shared bot's token.** Whoever holds the token can read every linked
  person's messages to the bot and send to any of them as the bot. A person cannot revoke it
  with @BotFather, because it is not theirs. Its custody is the relay's, outside this repository.
- **The relay can speak as a person to their hub.** It can fabricate a message from a linked
  account, and the hub will take it as that person's, carrying their authority (§5). What
  keeps the operator from doing so is #879's terms, "The operator never performs an act that
  carries the person's authority", and not a mechanism. ADR-0327 §13 says the same of the box.
- **Unchanged from ADR-0323 §14:** Telegram can read the chat, Telegram discloses to courts,
  account takeover is the practical risk (so two-step verification is recommended), and
  forgetting reaches what the assistant reads and not Telegram's copy.

> **Normative.** The relay keeps no copy of what a hub sends after the call that carries it
> ends, in any store, log or diagnostic.

> **Normative.** The relay deletes an update's message once the hub it was routed to has
> confirmed it, and keeps no other copy of it in any store, log or diagnostic.

These two rules keep the line's copies to the ones ADR-0323 already admits. The hub's episodes
are within #879's reading of ADR-0155 §1:1. Telegram's chat is admitted by ADR-0323 §16. A
relay keeping a third copy would hold the person's conversation outside both, where forgetting
cannot reach it.

> **Normative.** No clause, surface or message of the line states or implies that the hub can
> reach, bound or delete what the relay holds.

> **Normative.** For a relayed line, the note to the person states each cost in the list above
> before the line is connected, in place of ADR-0323 §14's bot-token item, which a relayed
> person's line does not have.

### 11. Setting it up, and whose act the approval is

For a hosted person:

1. **The person links their Telegram account** from their signed-in page, through the relay's
   flow. That act is theirs, behind their sign-in.
2. **The relay mints the hub's relay credential.**
3. **The operator, at the person's request, sets up the hub.** That means connecting the relay
   credential with `assistant connect` on the box, and writing the settings:
   `telegram_connection`, `telegram_user_id` (the linked account's id),
   `telegram_relay_origin` and `telegram_relay_certificates`.
4. **The note recommends Telegram's two-step verification** (ADR-0323 §3:4), and states §10's
   costs.

> **Normative.** In relayed mode the approval ADR-0323 §12:1 names rests on the person's own act
> of linking their Telegram account at the relay. The connect act and the line's settings are
> setup acts that the operator performs only at the person's request (#879), and they carry the
> approval out. Its destination is still the one chat the settings name.

> **Normative.** `telegram_user_id` names the account the person linked, and no other.

> **Normative.** In relayed mode the approval also ends when the person unlinks their account at
> the relay. The relay then serves that hub nothing and sends nothing on its credential.

> **Normative.** In relayed mode the user's act ADR-0323 §3:3 names, which creates the channel,
> declares its audience private and names the one chat, is the person's link act at the relay.
> The settings the operator writes at the person's request carry it out.

The person's act is recorded by the relay, outside this repository, and the hub records only the
setup. The link is still mechanically necessary: without it the relay serves the hub nothing and
refuses every send (§5:2, §6:1). So the hub's line carries nothing the person did not link.

The operator's own hub may use relayed mode too. Then the operator links their own account, and
these acts are all the operator's own. The hub builds no pairing flow (ADR-0323 §3:5); the
linking is the relay's.

### 12. The contract, the settings and the wire

| What | Where | Change, built by #3141 |
| --- | --- | --- |
| `TelegramBotClient`'s rule 5 | `core/protocols.py` | Restated as one request to the line's one origin: `https://api.telegram.org`, fixed in code, in direct mode; the configured relay origin, verified against the configured certificates alone, in relayed mode. Still on a channel per call, with no redirect followed, every call a `POST` |
| `TelegramBotClient`'s rule 3 and its summary | `core/protocols.py` | "The token" reads as the line's credential: the bot's token in direct mode, the relay credential in relayed mode. "The owner's bot" reads as the line's bot, the shared one in relayed mode |
| The contract's conformance suite | `tests/` | Gains relayed mode's obligations: §6:3's refusal, §7's anchors, and the origin |
| `HttpsTelegramBotClient` | `tools/egress.py` | Takes the origin it reaches at construction: the fixed one, or the canonical relay origin |
| A transport anchored on configured certificates | `tools/egress.py` | A `StreamOutboundTransport` whose TLS context trusts the given certificates alone (§7:3) |
| `telegram_relay_origin`, `telegram_relay_certificates` | `core/config.py` | New, with §3's structural refusals at load: text only, no canonicaliser (§3:5) |
| The line's wiring | `app/composition.py` | Canonicalises the relay origin through the seam and loads the certificates, refusing the hub's start on either failure (§3:4, §3:8), then builds the relayed client and its transport while `telegram_relay_origin` is set |

> **Normative.** The `TelegramBotClient` contract's rule 5 and rule 3 are restated as the table
> above states. That is a breaking contract change under golden rule 5, landing with its
> conformance suite as one change (ADR-0137 §2), in #3141's lane.

> **Normative.** No member of `TelegramBotClient`, no argument, no result and no
> `TelegramFailure` member changes for relayed mode. Relayed mode is configuration of the one
> production implementation at its construction.

> **Normative.** Relayed mode adds exactly the two `Settings` fields §3 names, and no others.

> **Normative.** Neither of the two fields is a credential. The relay credential is a connection's
> credential and never a setting (§6:4).

> **Normative.** No lane implementing this decision changes `PROTOCOL_VERSION` for it. It changes
> no shape the wire carries: no member of the connect exchange, no frame and no method's
> arguments or results (ADR-0124 §9). The settings, the client and its contract are inside the
> hub.

> **Normative.** Relayed mode is tested against a fake relay, never a real one. The tests cover:
> a certificate outside the configured set refused before any byte; a matching certificate for
> another host refused; a credential containing `:` refused before any byte; the relay's
> refusals and silences classified as §4's table states; no call reaching
> `https://api.telegram.org` in relayed mode; and no relay credential in any log line, record or
> error.

### 13. What this decides no part of

> **Normative.** This decision decides nothing of the relay's internals: how it receives
> updates from Telegram, how it stores its queue, how linking works, how it keeps the bot's
> token, how it stores credentials, or how its certificate is issued. It decides only what §4,
> §5:2, §6:1–§6:2, §7:5, §8:1, §10:1–§10:2 and §11:3 require of it. A lane that finds it needs
> one of those internals to be a particular way stops and raises it on #3140.

> **Normative.** It decides nothing about how #3142's containers are built, beyond §8:2.

### 14. Relationship to earlier decisions

ADR-0082 §1 has this text apply ADR-0070 §1's test: would a reader holding only the earlier text
now act differently? Where they would, the clause is superseded in part, recorded on that ADR's
status line and in a dated header note, atomically with this decision. Each replacement takes
effect when this decision is ratified.

> **Normative.** This decision supersedes, in part and only for a line in relayed mode, the
> clauses of ADR-0323 listed below, and no clause of any other ADR.

**Superseded in part, each for a line in relayed mode alone:**

| ADR-0323 | What changes |
| --- | --- |
| §2:1 | The bot is the shared one, which the person linked their account to, not one the user connected |
| §2:7, §5:5, §5:6, §5:7, §11:10, §13:1 | In their naming of Telegram as what the line's calls reach, alone: the relay stands in its place (§4:16) |
| §3:1 | The credential is the hub's relay credential, not the bot's token (§6:4) |
| §3:3 | Its *user's act* is the person's link act, carried out by the settings the operator writes at their request (§11:4) |
| §4:3 | Restated by §5:1: Telegram's report, as the relay hands it on |
| §11:4, §11:8, §11:9 | In the addition: they bind the relay credential as they bind the bot's token (§6:5, §6:6) |
| §11:5 | The one origin is the configured relay origin, verified against the configured certificates (§3:4, §7) |
| §12:1 | The approval rests on the person's link act, and the operator's setup carries it out (§11:1) |
| §12:3 | In the addition: unlinking at the relay ends the approval too (§11:3) |
| §13's table, rows 3, 4, 5, 7, 8, 10 and 12 | Restated for the relayed route by §9's table |
| §14:1 | For a relayed line, the note states §10's costs in place of the bot-token item (§10:4) |
| §14:2 | In the addition: nor what the relay holds (§10:3) |

**Engaged, examined, and not superseded:**

- **ADR-0323 §2:3**, the channel's identity, binds unchanged. §6:7 makes a mode change a new
  connection, and with it a new channel.
- **ADR-0323 §3:2**, **§3:4–§3:6**, **§4:1–§4:2**, **§4:4–§4:13**, **§5:1–§5:4**, **§5:8–§5:11**, **§6**,
  **§7–§10**, **§11:1–§11:3**, **§11:6–§11:7** and **§11:11–§11:14** bind a relayed line
  unchanged. The relay serves them faithfully (this decision's §4), and this decision's §5:3
  restates ADR-0323 §4 and §5 for the reader. ADR-0323 §3:5 stands: the hub builds no pairing
  flow. ADR-0323 §3:6 stands: disconnecting removes the relay credential.
- **ADR-0323 §12:2 and §12:4**, and **§15**, bind unchanged. This decision's §12 table is
  #3141's.
- **ADR-0323 §16**: its supersessions of ADR-0155, ADR-0148, ADR-0154, ADR-0292 and ADR-0321
  stand, and they reach a relayed line as they reach a direct one. The relay is on the box the
  hub is on, run by the same operator. Under #879's reading of ADR-0155 §1:1 it is not another
  party's service, and §10:1–§10:2 keep it from holding a copy beyond the call.
- **ADR-0191 §4:2** is kept (§7). **ADR-0191 §5:4** is not used (§8:4). **ADR-0191 §3** binds:
  the relayed transport is handed to the client by the composition root alone.
- **ADR-0231 §8** binds whole: the relay's origin is canonicalised by it, at the seam and not in
  `core` (ADR-0231 §8:7), and IP literals stay refused (§3:4–§3:5).
- **ADR-0174 §1:1**, as ADR-0327 §3:1 leaves it, is unchanged (§9:1).
- **ADR-0327** is unchanged. Its hosted listener stays plain HTTP. The context above states why
  this hop differs.
- **ADR-0125 §8** binds the relay credential (§6:4–§6:5).
- **ADR-0154 §4:1**: §9 is its ADR for the relayed route, as ADR-0323 §13 is for the direct one.

> **Normative.** This draft records its replacements on ADR-0323's status line and in a dated
> header note there, atomically with this ADR under ADR-0070 and ADR-0082, preserving ADR-0323's
> ratified body.

## Consequences

- **A hosted person messages one shared bot, and only their own hub answers.** Nothing in their
  hub's reader, writer or intake changes. The line is the same line, reached through the relay.
- **No hub holds the bot's token.** One program on the box does, and its custody is the relay's.
- **The operator's box holds everyone's Telegram conversation in transit.** The relay sees every
  message and can forge one. #879's terms, and not a mechanism, keep the operator from doing so
  (§10). The note to each person says so.
- **Two checks must agree.** The relay's linked account and the hub's `telegram_user_id` are
  set separately. When they differ, the line carries nothing (§5). When a person links a
  different account, the operator updates the hub's setting, and that is a new place (ADR-0323
  §2:3).
- **The operator holds one more setup act per hub**: the relay credential and the relay's
  certificate. Rotating the certificate is an act at every hub (§3:9).
- **Direct mode stays.** The owner's own hub, or anyone's, can keep a bot of its own.
- **Follow-on work.** #3141 builds §12's table, after this decision merges and after the learning
  walk's lane that holds `core/` and the line's users has landed. The private repository builds
  the relay and the linking against §4, §5:2, §6:1–§6:2, §7:5, §8:1, §10:1–§10:2 and §11:3.
  #3142 holds §8:2 for the containers.
- **Revisit** if the relay's custody costs more than the pilot can carry, if a person needs to
  revoke the bot themselves, or if Telegram offers a way to check its word past a relay. Each is
  a new ADR, not an edit of this one.

## Alternatives considered

- **A bot of each person's own, in direct mode.** No relay, and no new trust. But each person
  makes a bot with @BotFather and gives the operator its token. The owner ruled one shared bot.
- **Plain HTTP on the hop, as ADR-0327's hosted listener has.** Rejected (Context): the seam has
  no cleartext form, the credential is standing, and the response is what must be authenticated.
- **The relay signs every response with a key configured at setup**, ADR-0327's pattern turned
  around. It would need a scheme of our own that binds each response to its request, to stop an
  old "message from the person" being replayed, and the hop is TLS anyway. A TLS anchor
  configured at setup gives the same check, inside the channel.
- **A per-hub secret both ways**, as an HMAC on requests and responses. The same objections, and
  the secret sits at both ends.
- **Mutual TLS, with a client certificate per hub.** The transport has no client-certificate
  option, and adding one is a change to the `OutboundTransport` contract. A bearer credential
  inside verified TLS gives the relay the same assurance.
- **Trusting the system's certificate authorities for the relay.** Anyone able to get a publicly
  trusted certificate for the relay's name could stand in its place, and a name on a box's
  internal network has no public certificate to get.
- **An IP literal for the relay.** ADR-0231 §8 refuses one, for reasons that hold here. A host
  name the box's network resolves needs no change to the canonicaliser.
- **A Unix socket per hub, mounted into its container.** No network hop at all. But the seam's
  transport opens TCP endpoints only, and it would bind how the containers are built. It can come
  later without any change to §4.
- **The relay calling the hub (webhooks).** ADR-0323 §2:7 keeps the hub calling out, and a
  listener in the hub for the relay would be one more door.
- **The relay authenticating the hub by its network address.** Addresses on the box's internal
  network are assigned, not proven, and any container could claim one.
