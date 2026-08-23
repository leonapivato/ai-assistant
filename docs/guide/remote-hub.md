# The hub on another machine

You end this page with the hub running on one machine and your laptop asking it
things from another.

This is a different arrangement from [`phone.md`](phone.md) and the two do not
depend on each other. There, the hub and the gateway stayed together and a
*browser* moved. Here, the **hub** moves: it runs somewhere that is always on,
and the `assistant` command on your laptop reaches it across your overlay
network. You can do both, and then the gateway runs beside whichever browser
you want to use.

Do [`first-run.md`](first-run.md) first, on the machine that will hold the hub.
Everything below assumes it already works there.

## What moves and what does not

- **The data directory stays with the hub.** It never moves and is never shared.
  A client holds nothing.
- **The model key stays with the hub**, for the same reason it did before: the
  hub is the only process that talks to a model.
- **The gateway is a client**, so it can run on either machine. Running it on
  the laptop means the browser page is served locally and the hub is reached
  over the overlay.

Admission is **two facts**, and neither admits a client on its own: the caller
is at the overlay identity you enrolled, and it presents the credential that
enrolment minted. Being on the overlay is not enough — networks acquire members,
and the hub admits on a decision you made *at the hub*.

## 1. Turn on the hub's remote listener

On the hub's machine, add two settings to its `.env`:

```bash
ASSISTANT_HUB_REMOTE_ADDRESS=100.86.154.22
ASSISTANT_HUB_REMOTE_PORT=50084
```

The address is the **hub machine's** overlay address, a literal address rather
than a name, and it carries the same five refusals the gateway's does: not a
wildcard, not a loopback address, not multicast, not link-local, and not
reachable from the public internet. The local Unix socket stays bound as well —
turning this on adds a door, it does not move one.

Restart the hub. It now says so, and tells you its own overlay identity:

```text
hub_remote_bound   address=[redacted] hub_overlay_identity=n33u2icoEW11CNTRL
                   port=50084 max_connections=64
hub_admin_bound    socket=/home/you/.ai-assistant/admin.sock
hub_listening      socket=/home/you/.ai-assistant/hub.sock ...
```

The address is redacted in the record on purpose; you configured it, so you
know it.

`hub_admin_bound` is the line that matters for the next step. The hub binds that
socket **only when the remote listener is on**, because enrolling devices is
only meaningful when there is a door for them to arrive at — so
`ai-assistant-device` does not work on a hub that has not been through this
step, and says so rather than reporting the hub as not running.

## 2. Enrol the client, at the hub

Enrolling is an act you perform on the hub's own machine, with the hub
**running** — unlike the offline tools, this one asks the hub to change its own
record.

You need the client machine's overlay identity, read the same way
[`phone.md`](phone.md) reads a phone's: `tailscale status --json`, the `ID`
field of the right `Peer`.

```bash
ai-assistant-device enrol <the client machine's overlay identity>
```

```text
Device:     n33u2icoEW11CNTRL
Hub:        n33u2icoEW11CNTRL
Credential: 9-oZ2ybYgTfXzk2i2Q3BgUVzCziGDSVVnmkmW7aCAa4

Give the device both values. The credential is shown once and never again:
the hub keeps only a verifier it cannot be recovered from.
```

**The two identities above are equal only because that run had one machine
playing both roles.** On two machines `Device:` is the identity you passed in
and `Hub:` is a different value — the hub's own, the same one `hub_remote_bound`
printed in step 1. Read the labels, not the strings: what step 3 needs is the
`Hub:` line, and passing the `Device:` line there enrols the client at a hub
that is not the one it will dial.

Two values come out and the client needs **both**. If you lose the credential
it cannot be recovered — run `enrol` again for the same device, which mints a
new one and leaves the old verifying against nothing.

## 3. Store both values on the client

On the client machine:

```bash
assistant device enrol <the Hub: value from step 2>
```

It prompts for the credential without echoing it. To pipe it instead, add
`--credential-stdin` and give it on the first line of standard input.

```text
Enrolled. This device is now bound to hub n33u2icoEW11CNTRL.
Set ASSISTANT_REMOTE_HUB_ADDRESS to that hub's overlay address to reach it from
here. The address is where to dial; the identity above is what the answer has to
be, and changing one does not change the other.
```

Both values go into the client machine's OS keyring and nowhere else. They are
stored together, because holding one without the other is an incomplete
enrolment the client refuses to connect on.

## 4. Point the client at the hub

In the client's `.env`:

```bash
ASSISTANT_REMOTE_HUB_ADDRESS=100.86.154.22
ASSISTANT_REMOTE_HUB_PORT=50084
```

The ports must match. The address is where to dial; the enrolled identity from
step 3 is what the answer has to be, and the client checks the second before it
sends anything.

Setting `ASSISTANT_REMOTE_HUB_ADDRESS` is what selects the remote transport. A
client with it unset uses the local Unix socket and never touches the network.

```bash
assistant ask "Say READY."
```

```text
READY.
Plan: The goal is simply to say 'READY', which requires only a direct text
response with no external capability.
No action was needed.
```

## Managing enrolments

At the hub, with it running:

```bash
ai-assistant-device list
```

```text
Hub: n33u2icoEW11CNTRL
  n33u2icoEW11CNTRL  enrolled 2026-08-22T23:03:37.207312+00:00  live
```

`ai-assistant-device revoke <identity>` stops the hub admitting that device and
closes the connections it currently holds — which is why this tool needs the hub
running, where the offline tools need it stopped.

`assistant device unenrol`, run on the *client*, removes that machine's copy of
both values. The two acts are independent and you usually want both: revoking at
the hub cannot reach a keyring on another machine, and unenrolling on the client
does not stop the hub admitting it.

## What this page is not

This is the client-and-hub *protocol*, not a deployment manual. Getting a
machine to run a hub unattended — a service unit, restarts, backups, upgrades —
is an operating question, and this project's own answer to it is the
`just deploy-hub` recipe (`scripts/deploy_hub.py`), which is an operator tool
for this repository's own hosts rather than part of a first run.

## When it does not work

**The address and the identity disagree.** This is the common one, and nothing
is sent:

```text
The assistant hub is not reachable: 100.122.70.4:50084 is the overlay node
'nkStNzztF421CNTRL', and this device was enrolled at 'n33u2icoEW11CNTRL'.
Nothing has been sent. Changing the address does not change the identity it has
to match (ADR-0124 §4): point ASSISTANT_REMOTE_HUB_ADDRESS at your hub, or enrol
this device at the hub you meant
```

Read it literally: it is telling you which node actually answers at the address
you configured. In the run above, the cause was an `ASSISTANT_REMOTE_HUB_ADDRESS`
exported in the shell, silently outranking the `.env` line — environment
variables win, always.

**`device: no hub is listening at …/admin.sock`.** It talks to the hub's admin
socket in the data directory, so it must run on the hub's machine, in a
directory whose `.env` names that data directory, with the hub running. If the
hub *is* running you get the other message instead — *“a hub is running here …
but it bound no control socket … because it has no remote listener
configured”* — which means the hub has not been through step 1: that socket is
bound only when the remote listener is configured on.

**The client is enrolled but nothing works after a machine rename.** The
identity is the overlay's stable node identifier, not a name or an address, so
renaming changes neither. If it genuinely changed — the node was deleted and
re-added — enrol again.
