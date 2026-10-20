# A hosted person's Telegram line, through the relay

This page sets up a hosted person's Telegram line. When it is done, the person
messages the shared bot and only their own hub answers.

Read [`container.md`](container.md) first: the hub here is the one it runs. The relay is
the box's own program, from the private operations repository, and its runbook covers
how it runs. This page covers the hub's side only (ADR-0330).

## The two modes

A hub's Telegram line runs in one of two modes, set by its settings at start:

- **Direct**, the default. The hub holds its own bot's token and reaches Telegram
  itself. This is the owner's line, as ADR-0323 builds it.
- **Relayed.** The hub reaches the relay on the box, which holds the shared bot. The
  hub holds a **relay credential**: the value the relay minted for this one hub, which
  is never a bot token. The hub trusts the relay through the relay's CA certificate,
  written into its settings, and never through the system's certificate authorities.

A line is relayed exactly when `ASSISTANT_TELEGRAM_RELAY_ORIGIN` is set. The two modes
are separate connections, so moving a line from one to the other is a new connection
and starts the line fresh. You never reprovision a bot-token connection with a relay
credential, or the reverse (ADR-0330 §6:7).

## Setting a person's line up

Do this at the person's request, in this order.

**1. Connect the relay credential to the hub, as a new connection.** The relay writes
the credential once, and only to a pipe:

```bash
sudo -u relay relay hub add --hub alice \
    | docker exec -i hub-alice assistant connect telegram-relay --credential-stdin
```

`telegram-relay` is the connection's identity: the name you will recognise it by in
`assistant connections`. The command prints the connection's **reference**, which you
need in step 3. Read it back at any time with:

```bash
docker exec hub-alice assistant connections
```

Nothing is armed yet. The line stays off until its settings are written.

**2. The person links their Telegram account** from their signed-in page. Linking is
their own act, and the relay records it. The hub sees nothing of it.

**3. Write the line's four settings** into the person's env file (`hub.env`), then
restart the hub through its deploy:

```bash
ASSISTANT_TELEGRAM_CONNECTION=<the reference step 1 printed>
ASSISTANT_TELEGRAM_USER_ID=<from: sudo -u relay relay hub show --hub alice>
ASSISTANT_TELEGRAM_RELAY_ORIGIN=https://telegram-relay:8443
ASSISTANT_TELEGRAM_RELAY_CERTIFICATES=<the relay's CA certificate, on one line>
```

- **`..._USER_ID`** is the Telegram account the person linked, and no other. The relay
  shows it only once the link is confirmed. If it differs from the linked account, the
  line carries nothing: the hub takes no message as the person's, and the relay
  refuses every send.
- **`..._RELAY_ORIGIN`** is the same for every hub on the box. The container setup
  makes `telegram-relay` resolve to the relay (`--add-host`). The origin must name a
  host, never an IP address, and must not carry a path.
- **`..._RELAY_CERTIFICATES`** is the relay's **CA** certificate, as `relay cert
  show` prints it, never the relay's leaf. An env file holds one line per variable,
  so remove the certificate's line breaks when you write it:

  ```bash
  printf 'ASSISTANT_TELEGRAM_RELAY_CERTIFICATES=%s\n' \
      "$(sudo relay cert show | tr -d '\n')" | sudo tee -a /srv/hubs/alice/hub.env
  ```

  To hold two certificates during a rotation, separate them with a comma.

**4. Tell the person what the line costs**, before it carries anything. This note
replaces the bot-token item in the direct line's note (ADR-0330 §10):

- The relay reads every message on the line. It runs on the operator's box, holds the
  shared bot's token, and could forge a message from the person. What keeps the
  operator from doing so is the hosting terms, not a mechanism.
- The person cannot revoke the bot with @BotFather, because the bot is not theirs.
- Telegram reads the chat too, and discloses to courts. Turning on Telegram's two-step
  verification is recommended.
- Forgetting reaches what the assistant holds, never Telegram's copy.

## Rotating the relay's CA

Rotating the CA is an act at every hub (ADR-0330 §3:9). Add the new CA's certificate
beside the old one, comma-separated, and restart the hub. Once the relay no longer
presents a certificate from the old CA, remove the old one and restart again. A new
leaf from the same CA needs nothing at the hub.

## When it does not work

A relayed line that cannot be started refuses the hub's start. The hub prints a
`hub: cannot start:` line, and the container exits `78`.

| The log says | What to change |
| --- | --- |
| `telegram_relay_origin is set and the Telegram line is not` | Set `..._TELEGRAM_CONNECTION` and `..._TELEGRAM_USER_ID` too. |
| `telegram_relay_origin is set and telegram_relay_certificates is empty` | Write the relay's CA certificate. |
| `telegram_relay_certificates is set and telegram_relay_origin is not` | Set the origin, or remove the certificates. |
| `telegram_relay_certificates[N] is not one certificate in PEM` | Copy `relay cert show`'s output whole, with its `BEGIN` and `END` lines. Remove the line breaks, not the armour. |
| `the Telegram line's relay cannot be reached as configured: telegram_relay_origin has no canonical form` | Write `https://telegram-relay:8443`: a host name, a port, and no path. |
| `… telegram_relay_certificates: certificate N could not be loaded as a trust anchor` | The text is not a certificate. Copy it again from `relay cert show`. |

Once the hub is up, a line that is not working logs it on each call:

- **`telegram_line_unavailable` with `reason=bot_token_on_a_relayed_line`.** The
  connection holds a bot token, and a relayed line never hands one to the relay.
  Connect the relay credential as a new connection (step 1), and point
  `..._TELEGRAM_CONNECTION` at it.
- **`telegram_call` with `outcome=not_written`, on every call.** The relay's
  certificate did not verify against the configured CA, or the relay is not
  listening. Check `sudo relay check` on the box, and check that the certificate
  configured is the CA from `relay cert show`.
- **`telegram_call` with `outcome=refused` on every poll.** The relay does not know
  this hub's credential, because it was rotated, reset or removed at the relay. After
  `relay hub rotate`, give the same connection the new credential with
  `assistant reconnect`. After `relay hub reset` or `relay hub add`, connect it as a
  new connection (step 1).
- **`telegram_call` with `outcome=rate_limited` on every call.** The relay's gate is
  shut, for example while the edge is down. The line retries by itself.
