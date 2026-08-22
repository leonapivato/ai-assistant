# The same page on your phone

You end this page with the assistant open in your phone's browser, reaching the
gateway on your laptop across your own private network.

Do [`first-run.md`](first-run.md) first. This page changes three settings and
restarts the gateway; everything else stays as it was.

## What this is, and what it is not

The gateway grows a **second listener** on an overlay address. It is still the
same gateway, still serving the same page, still talking to the same hub.

It is not a way to put the assistant on the internet. The second listener binds
an address that exists only inside your overlay network, and it is checked
twice: a wildcard, a loopback or a publicly routable address is refused when the
settings load, and an address that is not one the overlay agent on this machine
reports — your `eth0` address, say — is refused when the gateway starts, before
it binds anything. Putting a proxy or a tunnel in front of the loopback listener
is not a supported route to the same place either, and is refused for a
mechanical reason as well as a policy one: a terminating proxy destroys the fact
the gateway uses to tell your phone from anything else.

Two user-visible things are unavailable over this listener, because a page
served over plain `http://` from an address that is not loopback is not a
"secure context" as browsers define it: **operating-system notifications** (the
page's own in-page notices are unaffected) and **microphone capture**. That is a
known and decided cost, with its own trigger for reopening, rather than a bug
(ADR-0174 §7).

## 1. Put both devices on one overlay network

Use [Tailscale](https://tailscale.com/). **In practice it is required**, and it
is worth being exact about why, because the decision behind this and the code
implementing it say different-sounding things.

What the decision requires is a *property*, not a vendor: an overlay that
authenticates every participant before a byte is exchanged, encrypts end to end
between the two devices with no third party holding a key, and is administered
by you (ADR-0174 §2). Nothing is conditioned on Tailscale, and moving to another
overlay with those properties reopens no decision.

What the code speaks today is Tailscale's local API. The gateway asks the agent
on its own machine who is at a connecting address, and it asks over Tailscale's
`whois` endpoint at Tailscale's socket paths, reading Tailscale's `StableID`.
The socket path is configurable — `ASSISTANT_CLIENT_OVERLAY_AGENT_SOCKET` — but
whatever is behind it has to answer that API. So another overlay is a change to
this system, not a configuration of it, however well it satisfies the property.

Install it on the laptop and on the phone, and sign both into the same tailnet.
Then, on the laptop:

```bash
tailscale status
```

```text
100.86.154.22  laptop            you@  linux  -
100.78.9.87    iphone-13-pro     you@  iOS    -
```

The laptop's address on the first line is the address the gateway will bind.

## 2. Find your phone's stable identity

The gateway does not admit a browser because it is *on* the overlay. It admits
one because **you named that device**, at the gateway, in its configuration.
What you name it by is the overlay's own stable identifier for the node — not
its name and not its address, both of which can change.

```bash
tailscale status --json
```

Look for your phone under `Peer`, and take its **`ID`**:

```json
{
  "ID": "nPc1nAnbd411CNTRL",
  "HostName": "localhost",
  "DNSName": "iphone-13-pro.tail2e4542.ts.net.",
  "TailscaleIPs": ["100.78.9.87", "fd7a:115c:a1e0::ab01:9cb"],
  "OS": "iOS"
}
```

**Match on `DNSName` or `TailscaleIPs`, not on `HostName`.** An iPhone reports
its `HostName` as `localhost`, which is unhelpful and looks alarming; the table
`tailscale status` prints uses the `DNSName`, which is why the two disagree.

While you are here, note the laptop's own `DNSName` — `laptop.tail2e4542.ts.net`
in this example. You will want it in step 3.

## 3. Add three settings

In the same `.env` you wrote in `first-run.md`:

```bash
ASSISTANT_GATEWAY_REMOTE_ADDRESS=100.86.154.22
ASSISTANT_GATEWAY_REMOTE_BROWSER_DEVICES=nPc1nAnbd411CNTRL
ASSISTANT_GATEWAY_REMOTE_HOST_NAMES=laptop.tail2e4542.ts.net
```

- **`ASSISTANT_GATEWAY_REMOTE_ADDRESS`** is the switch. Unset, there is no
  second listener at all. It is the **laptop's** overlay address — a literal
  address, never a name — and the port is the same `ASSISTANT_GATEWAY_PORT` the
  loopback listener uses. There is no second port setting.
- **`ASSISTANT_GATEWAY_REMOTE_BROWSER_DEVICES`** is the permission, and it is
  comma-separated. Empty is the default and means *no device may start a
  session*, so a listener configured on with nobody listed serves the page and
  admits nobody. Listing a device is not an enrolment and grants nothing else:
  it is read as a set, order and repeats mean nothing, and no element is matched
  by prefix or pattern.
- **`ASSISTANT_GATEWAY_REMOTE_HOST_NAMES`** is optional and is a convenience.
  It lets you type the MagicDNS name into the phone instead of the numeric
  address. The gateway resolves nothing — a name here is accepted as a `Host`
  header value and is never used as a destination.

The two lists are **refused at load while the address is unset**, rather than
being ignored:

```text
Error: invalid configuration: 1 validation error for Settings
  Value error, gateway_remote_browser_devices=['nPc1nAnbd411CNTRL'] is set while
  gateway_remote_address is unset, so the remote browser listener it grants a
  permission on is off and nothing would ever read it (ADR-0174 §8). Set
  gateway_remote_address to the overlay address the gateway should serve
  browsers on, or unset gateway_remote_browser_devices
```

## 4. Restart the gateway, and read what it prints

Stop the gateway with `Ctrl-C` and start it again. It now discloses **every**
origin it can be reached at:

```text
Assistant gateway listening on http://127.0.0.1:8422,
http://100.86.154.22:8422, http://laptop.tail2e4542.ts.net:8422
Bootstrap value (good once, and only for this gateway process):
pDSYe-a4xKAcwzG_nJMU0vvgpQ1fN0cTHfQCqNwDOGc
```

Copy one of those origins. That is the address you type on the phone, and it is
the whole reason this line exists — you should not have to reassemble it from
two settings.

## 5. Open it on the phone — and type the `http://`

Type the origin into the phone's browser **including the scheme**:

```text
http://100.86.154.22:8422
```

Two reasons the scheme is worth typing rather than leaving to the browser. A
bare `100.86.154.22:8422` in a phone address bar is as likely to be treated as a
search as an address. And `https://` does not work here and is not meant to:
this listener speaks plain HTTP, and a browser given `https://` gets an
immediate failure rather than a page. (It is an immediate one — the gateway
answers a TLS handshake with `400 Bad Request` in a fraction of a second rather
than leaving the browser to time out.)

If you configured `ASSISTANT_GATEWAY_REMOTE_HOST_NAMES`, the MagicDNS origin
works identically and is much easier to type.

**Pick one of the two and stay on it.** A session belongs to the origin it was
minted at, so a session started at the numeric address does not admit at the
MagicDNS name. With one bootstrap value per gateway process, the second
authority cannot get a session at all without a restart.

## 6. Paste the bootstrap value

Same panel, same field, same rule: it is good once, and there is one per gateway
process. So today you choose — laptop or phone — and restarting the gateway is
how you change your mind.

> **This is the part that changes next.** #1429's ruling 1 has the gateway mint
> a fresh bootstrap value on demand, without a restart, so the laptop and the
> phone can both hold a session at the same time. That lands with lane 2 of
> milestone 16.

Getting the value onto the phone is your problem and worth a moment's thought:
it admits a browser to everything the assistant can do. Reading 43 characters
off the laptop screen is the boring answer and a perfectly good one.

## Why your phone had to be listed

Being on the overlay gets your phone the page. It does not get it a session.

- Any device on your overlay may fetch the page, the stylesheet and the script.
  Those carry nothing — no assistant content, no fact about the hub.
- **Only a listed device may exchange a bootstrap value.** An exchange from an
  unlisted device is refused with `403 Forbidden` *without the value being read
  or spent* — so an unlisted device that somehow got hold of your bootstrap
  value cannot burn it, and the value still works when you use it yourself.

That split is deliberate (ADR-0174 §4). Networks acquire members — an ACL edit,
a device you added for something else — and admitting on membership alone would
mean the gateway admitting on a decision you never made at the gateway.

## When it does not work

**`gateway_remote_address='8.8.8.8' is reachable from the public internet`** —
you gave it something that is not an overlay address. The message goes on:
*"where the population that can attempt the credential is everyone — which is
the door ADR-0124 §2 refuses to open. Configure the address your overlay agent
reports for this machine."*

**`gateway_remote_address='127.0.0.1' is a loopback address, which is not on the
overlay`** — the loopback listener is a separate thing and is always bound.
This setting is for the *other* address.

**The page loads on the phone, and `Start` answers `The gateway refused that
request (HTTP 403).`** Your phone is not in
`ASSISTANT_GATEWAY_REMOTE_BROWSER_DEVICES`, or it is in there under the wrong
identifier. Check the `ID` you took in step 2 — `HostName` is the wrong field,
and so is the address. The page cannot currently be more specific than that
(#1438); the gateway's own answer names the condition, `device-not-listed`.
Your bootstrap value is untouched and still works.

**The phone cannot reach the address at all.** That is the overlay, not the
gateway. `tailscale status` on the phone, and check the laptop is not asleep.

**The gateway prints only the loopback origin.** `ASSISTANT_GATEWAY_REMOTE_ADDRESS`
did not load. Check you edited the `.env` in the directory you start the gateway
from, and that no environment variable of the same name is overriding it.
