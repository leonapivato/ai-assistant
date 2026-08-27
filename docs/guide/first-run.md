# First run

You end this page having asked the assistant something in a browser.

Two terminals, and they both stay open. The first runs the hub; the second runs
the gateway. Nothing here daemonises itself, and neither process starts the
other.

## 1. Pick a directory to run from

Configuration is read from a file named `.env` **in the directory you run the
command in**. That is a genuinely relative path, so the same command in two
directories loads two configurations. Pick one directory, and run everything on
this page from it.

```bash
mkdir -p ~/assistant && cd ~/assistant
```

This is not the data directory — it is just where the configuration file lives.

## 2. Write the configuration

```bash
cat > .env <<'EOF'
ASSISTANT_DATA_DIR=~/.ai-assistant
ASSISTANT_DEFAULT_MODEL=anthropic:claude-sonnet-4-5
ASSISTANT_TIMEZONE=Europe/Rome
EOF
```

That block is meant to be pasted as it stands. The one thing to change is the
timezone, if Rome is not where you are. Output quoted further down shows paths
under `/home/you/` — that is this guide's stand-in for your own home directory,
which is what `~` above expands to.

Three settings, and each of them says something the system cannot guess.

- **`ASSISTANT_DATA_DIR`** is the directory the hub owns exclusively — its
  SQLite stores and its instance lock. It must be **absolute**; `~` is expanded
  for you, and a relative path is refused at load rather than resolved, because
  the hub and a client run from different directories and would disagree about
  where it points. Omit the setting entirely and you get `~/.ai-assistant`,
  which is a fine answer; name it explicitly if you want it somewhere else.
- **`ASSISTANT_DEFAULT_MODEL`** is a `provider:model` route. The assistant is
  model-agnostic: this is where you choose. `anthropic:…` and `openai:…` are
  the two whose vendor libraries ship in the wheel.
- **`ASSISTANT_TIMEZONE`** is an IANA name, and it is what "this afternoon"
  means to the assistant.

The repository's [`.env.example`](../../.env.example) is the full menu — every
setting that arms a feature, with a comment saying what it arms. You do not
need any of the rest yet.

**An environment variable beats this file.** If `ASSISTANT_DEFAULT_MODEL` is
already exported in your shell, the `.env` line is not what loads. That is worth
knowing before you spend twenty minutes editing a file that is not being read.

## 3. Put the model key in the environment — not in `.env`

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

This one is different from everything else on the page and the difference
matters, because getting it wrong produces a hub that will not start.

`.env` is read by this system's own settings loader, and that loader reads
`ASSISTANT_*` names and ignores everything else. It does not copy anything into
the process environment. The **model key is not read by this system at all** —
it is read straight from the process environment by the provider library that
makes the call. So a key written into `.env` reaches nobody:

```text
hub: cannot start: model spec 'anthropic:claude-sonnet-4-5' names provider
'anthropic', for which this deployment holds no credential: Set the
`ANTHROPIC_API_KEY` environment variable ...
```

Export it in the shell you start **the hub** in. The hub is the only process
that talks to a model; the gateway and the command-line client never do, and
neither needs the key.

The key is not put in the OS keyring either, and that is deliberate rather than
an omission. The keyring holds secrets this system mints and owns. A provider
key is credential material the provider library expects to find in the
environment, and moving it would mean this system handing it back to that
library anyway.

## 4. Start the hub

In the first terminal:

```bash
ai-assistant-hub
```

It prints structured records and then stays in the foreground. The two lines
worth reading are the first two:

```text
hub_listening   socket=/home/you/.ai-assistant/hub.sock max_connections=64 ...
hub_ready       data_dir=/home/you/.ai-assistant pid=3941190 remote=None
                jobs=['retention_purge', 'conversation_sweep',
                'notification_reconsider']
```

`remote=None` means it is listening on its local socket only — no network
listener of any kind. That is the default and it is what you want on one
machine. [`remote-hub.md`](remote-hub.md) is the other case.

The data directory now exists, with one file per store plus the lock and the
socket:

```text
audit.db  connections.db  conversations.db  deferrals.db  grants.db
memory.db  notifications.db  outbox.db  plans.db  reads.db
traces.db  hub.lock  hub.sock
```

All of them are `0600`. `hub.lock` is what stops a second hub taking the same
directory.

## 5. Ask it something from the command line

Leave the hub running and open a **second terminal**, in the same directory:

```bash
cd ~/assistant
assistant ask "In one short sentence, what is the capital of Italy?"
```

```text
The capital of Italy is Rome.
Plan: The question asks for a factual answer about the capital of Italy, which
can be directly answered from general knowledge without requiring any external
capability.
No action was needed.

Conversation: 60a9b895-1e9e-4ca1-8afd-6dfd6e415809  (continue with: assistant
ask --conversation 60a9b895-1e9e-4ca1-8afd-6dfd6e415809 ...)
```

This is the cheapest possible proof that the two hard parts are right: the
client reached the hub, and the hub reached a model. If this works, everything
that follows is about the browser and nothing else.

## 6. Start the gateway

Still in the second terminal:

```bash
assistant gateway
```

```text
Assistant gateway listening on http://127.0.0.1:8422
Bootstrap value (good once, and only for this gateway process):
GxiDDPy-iKHkzc5led4fxv9UwGo5bFs73s-ZU9-UWms
Live sessions: 0 of 8. For another value: kill -SIGUSR1 3941204
```

That last line is the gateway saying how many browsers it is already serving and
how to get another value. Step 7 is where both matter; for now, note that
`3941204` is **this** gateway's process id, and yours will be a different number.

Leave it running too. It binds `127.0.0.1` and nothing else, on port 8422 by
default (`ASSISTANT_GATEWAY_PORT` moves it). The address is not configurable —
no setting can widen the loopback listener, and that is a decided property
rather than an oversight (ADR-0168 §2).

The gateway starts whether or not the hub is running. That is on purpose: a
browser that reaches a gateway with no hub behind it is told the hub is down,
which is a different and more useful thing than a browser that reaches nothing.

## 7. Open the page and paste the value

Open **`http://127.0.0.1:8422`** in a browser on this same machine.

The page shows one panel, **Start a session**. Paste the bootstrap value into
the *Bootstrap value* field and press **Start**.

**Start** posts the value to `/session`, as `{"bootstrap_value": …}`. A gateway
that accepts it answers with the two halves of a session and nothing else: a
`header_half` in the JSON body, which the page keeps and sets as the
`X-Assistant-Session` header on every later request, and an `assistant_session`
cookie the browser attaches on its own. Every admitted request carries both
halves (ADR-0168 §6) — so a client that finishes this step without a browser has
to store a cookie as well as set a header.

That value is good exactly once, and it is good for ten minutes. The gateway
mints one when it starts, prints it on standard output, and never prints that
one again — not in a log record, not in an error, not in any page. Exchanging it
gives this browser a session; a second exchange of the same value is refused:

```text
HTTP/1.1 400 Bad Request
```

### If you lose it, ask for another one

You do not restart the gateway. Send it `SIGUSR1`, from any terminal on the
machine it runs on and as the user that started it — the process id is on the
last line it printed:

```bash
kill -SIGUSR1 3941204
```

It prints a fresh value on its own terminal, straight away:

```text
Assistant gateway listening on http://127.0.0.1:8422
Bootstrap value (good once, and only for this gateway process):
IznwmhTUYUKp04I8Z_BfM8_tMFKYaCrDZqcFm_wCNGQ
Live sessions: 1 of 8. For another value: kill -SIGUSR1 3941204
```

Nothing restarts and nothing is logged out: a browser that already has a session
keeps it. That is also how a **second** browser joins a running gateway, which is
the last step of [`phone.md`](phone.md).

> **Send it only when the gateway offered it.** `For another value: kill -SIGUSR1
> …` is printed by a gateway that can perform the act, and left out entirely by
> one that cannot — the line is the offer, and its absence is the refusal
> (ADR-0182 §1). Such a gateway also says so at start, in a note that tells you
> whether `SIGUSR1` is now harmless or would **stop the gateway and end every
> session with it**. So: no line, no signal. Restart it instead, and see *When it
> does not work* below.

Three things about that act, and none of them is incidental.

- **It is a signal, not a command and not a URL.** Every process on this machine
  can reach the gateway's port, so minting is put behind something only you and
  root can do *here* (ADR-0182 §1). There is no `assistant gateway mint`, and no
  request on any listener mints a value.
- **One value stands at a time.** A fresh mint replaces the outstanding one, so
  the value on your screen is always the value that works. Mint twice and the
  first of the two has stopped admitting anything.
- **`Live sessions: 1 of 8`** is how many browsers already hold a session,
  against `ASSISTANT_GATEWAY_MAX_SESSIONS`. It is information rather than a
  refusal: the gateway mints whatever that count is, and it is the *exchange*
  that is refused when the table is full.

**A value nobody spends dies after ten minutes**
(`ASSISTANT_GATEWAY_BOOTSTRAP_TTL`). Long enough to carry it to another device
and retype it; short enough that one left in a terminal's scrollback is dead well
before you have scrolled past it. Four things end a value and there is no fifth:
spending it, those ten minutes, a fresh mint replacing it, and the gateway
process ending.

## 8. Ask it something in the browser

The **Ask** panel takes the bootstrap panel's place once the session exists.
Type into *What do you want the assistant to do?* and send it. The answer
arrives on the page as it is composed rather than in one piece at the end.

Or **hold to talk**, under the box: hold the button down, speak, and let go. The
recording goes up when you release and the answer comes back on that request —
shown in the panel exactly as a typed question's is, and spoken aloud as it
arrives. Under the button you get `Heard: …`, the transcript the assistant worked
from, so an answer to the wrong question is something you can see the cause of.

Two things it may say instead, neither of which is a failure: *"I heard
nothing"*, meaning the press caught no words and nothing was asked; and *"that
answer is shown here and was not spoken"*, meaning the answer is complete on
screen and only the audio is missing. Nothing of the recording is kept anywhere.
If the button is greyed out, the page says why under it — the browser hands a
microphone only to a page it considers secure, which this one is and the
`http://` address of another machine is not
([`phone.md`](phone.md) sets up the one that works).

That is the whole of the first run. The rest of the page is the control surface
over what the assistant remembers, what it may read, and what it is holding to
tell you — every one of those is also an `assistant` subcommand, and they are
the same acts either way.

## What a session is, and when it ends

Three facts, because all three surprise people.

- **Every session ends when the gateway process does.** Stopping the gateway
  with `Ctrl-C` ends every session it minted, in every browser. It says so on
  the way out: `Gateway stopped. Every session ended with it.` This is a
  decided property (ADR-0168 §4) — the session lives in the gateway's memory
  and is not written down anywhere.
- **A session ends after an hour of not being used.** The idle timeout is one
  hour by default (`ASSISTANT_GATEWAY_SESSION_IDLE_TIMEOUT`). A tab left open
  overnight comes back needing a fresh bootstrap value — `kill -SIGUSR1` at the
  gateway, as in step 7, and no restart.
- **And in any case after twelve hours.** The ceiling is twelve hours from the
  moment it was minted, however busy it was
  (`ASSISTANT_GATEWAY_SESSION_TTL`). A session ends at whichever of the three
  comes first.

Reloading the page does **not** end a session. The browser holds the session
across a reload, so a refresh costs you nothing. **Closing the browser** is a
different matter: half of the session is a cookie that does not outlive the
browser, so the next launch needs a fresh bootstrap value even if the gateway
never stopped. Again: step 7's mint act, not a restart.

## Stopping

`Ctrl-C` in each terminal, gateway first if you care about the order. The hub
finishes what it is doing and releases its lock. Neither leaves anything
running behind it.

`hub.sock` goes when the hub stops accepting; **`hub.lock` stays**, and a file
left there is not a stale hub. What a hub holds is a kernel lock on that file,
released the moment the process ends however it ends — so the file's presence
says nothing about whether one is running, and deleting it by hand is what could
let two hubs end up holding the same directory at once (ADR-0083 §1).

## When it does not work

**`The assistant hub is not reachable: no assistant hub is listening at
/home/you/.ai-assistant/hub.sock.`** The hub is not running, or it is running
against a different data directory. The message continues: *"Start it with
'ai-assistant-hub' and leave it running, then try again. (This client never
starts one for you, and never falls back to running the assistant
in-process.)"* — which is the whole design in one sentence.

**`hub: cannot start: … for which this deployment holds no credential`** The
model key is not in the hub's environment. See step 3 — a key in `.env` does
not count.

**`invalid configuration: 1 validation error for Settings`** A setting is
malformed. The message names the field, quotes the value it got, and says what
would be acceptable; the fix is almost always in that sentence.

**`Error: the gateway could not bind port 8422 … address already in use`.**
Something else already holds that port — most often another gateway you forgot
about. Stop it, or set `ASSISTANT_GATEWAY_PORT` to a free port — in the `.env`
from step 2, or exported in the shell you start the **gateway** in. The gateway
prints its bootstrap value *before* it binds, so there will be one on the screen
above the error: it went with the process that failed to start, and the next
gateway prints its own. (Once you have done [`phone.md`](phone.md) the wording
changes a little, because there are then two listeners on that port and either
could be the one refused.)

**`This gateway could not install the mint act …`**, printed at start, and no
`For another value:` on its disclosures. It is serving normally and every browser
it admits is fine, but it can mint nothing further — **restarting it is the only
way to another bootstrap value**, and that ends every session it is holding. Read
the whole line before you do anything else: it says either that `SIGUSR1` has been
made harmless, or that sending it would stop the gateway and end every session
with it. In the second case do not send it. This is rare and is not about your
configuration — it is the gateway being started somewhere it could not take a
signal disposition.

**Nothing happens in the browser and the page keeps showing *Start a
session*.** The value was already spent, its ten minutes ran out, a later mint
replaced it, or the gateway was restarted after it printed. The gateway will not
say which — a failed exchange discloses only that it failed. Mint a fresh value
as in step 7 and use that one.

Next, if you want the same page on a phone: [`phone.md`](phone.md).
