# The same page on your phone

You end this page with the assistant open in your phone's browser, reaching the
gateway on your laptop across your own private network.

Do [`first-run.md`](first-run.md) first. This page obtains one certificate,
changes five settings and restarts the gateway; everything else stays as it was.

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

The second listener serves **HTTPS**, and that is a property of the listener
rather than a setting: nothing configures it to speak plain HTTP, it does not
fall back to one, and it serves no redirect from one. It terminates TLS itself,
in the gateway's own process, on a certificate your overlay obtains for this
machine's own overlay name and a private key that never leaves the machine —
step 3 (ADR-0202 §1, §2).

**A gateway that cannot do that does not start**, and says why. A missing,
unreadable, mismatched or expired certificate takes the whole gateway down,
loopback listener included. That is chosen rather than an accident: the
alternative is a gateway that starts, serves the local browser, and leaves your
phone with a page that will not load and nothing anywhere saying why (ADR-0202
§2). Step 5 is where you read how long the certificate has left, so the day it
runs out is a date rather than a surprise.

What the certificate buys is a **secure context**, and nothing about the wire
changes to get it. The overlay already encrypted every byte end to end between
the two devices and it still does; what was missing was that the browser had no
way to *know* it, so it withheld the capabilities it reserves for trustworthy
origins — microphone capture among them. With the classification in hand it
stops withholding them.

That is a precondition and not a feature: the page does not capture a microphone
today, and this decision does not decide that it ever will (ADR-0202 §9).
Entering a credential is still a loopback-only act, on a separate rule of its own
(ADR-0177 §3).

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

## 3. Get a certificate for the laptop's own name

The overlay obtains it, on the laptop, for the laptop's own overlay name — the
`DNSName` you noted in step 2. With Tailscale that is one command, run in a
directory you are happy to keep the files in:

```bash
tailscale cert laptop.tail2e4542.ts.net
```

```text
Wrote public cert to laptop.tail2e4542.ts.net.crt
Wrote private key to laptop.tail2e4542.ts.net.key
```

It needs HTTPS enabled for your tailnet, which is a switch in the admin console;
if the command tells you so, that is where to go. The certificate comes from a
**public** certificate authority — one your phone already trusts, with nothing
to install on the phone and nothing for you to click past. That is what makes
this worth doing at all: a certificate you signed yourself would train you to
overrule the browser's own trust decision, which is the mechanism you are here
to buy (ADR-0202 §1).

As in step 1, the requirement is a property rather than a vendor: an overlay
that obtains, for a name it assigns, a certificate from an authority the
browsing device already trusts out of the box. One that runs its own private
authority does not satisfy it — you would get the same warning and the same
withheld microphone, which is the self-signed route by a longer road (ADR-0202
§1).

**The key is a secret, and the certificate's integrity matters too.** The key is
of the same class as the memory database, so it lives owner-only:

```bash
chmod 0600 laptop.tail2e4542.ts.net.key
```

What the gateway checks is the **owner and the mode**, and it is worth knowing
exactly what that is and is not. It refuses to start on a key whose mode grants
any permission at all to group or other, and on a certificate whose mode grants
group or other **write**; world-*readable* is fine for the certificate, which is
public by construction. It refuses either file owned by another user, and either
sitting under a directory an untrusted user could swap it out through (ADR-0202
§3).

**That is not a check that nobody else can read the key, and it is not offered as
one.** A POSIX ACL granting another local user access survives an owner-only mode,
and this system reads no ACLs — a filesystem walk "can be wrong: a bind mount, an
ACL, a symlinked ancestor" (ADR-0084 §1), so it is defence in depth rather than
the thing that protects the key. What protects the key is that it is on your own
machine, owned by your own user. Keep both files somewhere only you can write to,
and if you have handed anyone else access to that directory, the mode will not
take it back.

**Nothing renews them for you.** Renewal is your act — run `tailscale cert`
again — and a renewed certificate takes effect the next time the gateway starts.
Nothing in this system watches the files, requests a certificate or talks to
your overlay's control plane (ADR-0202 §4).

**Two things become known, and both are accepted rather than hidden.** Your
overlay's operator learns that a certificate was obtained for this machine and
when; and, because the authority is a public one, the machine's overlay name
goes into a public certificate-transparency log. A reader of that log learns that
a machine by that name exists — no address anyone can route to, nothing about
what it does, and no door that was not already exactly where it was. If the name
itself says something about you that you would rather it did not, the tailnet
name is yours to choose (ADR-0202 §4).

## 4. Add five settings

In the same `.env` you wrote in `first-run.md`:

```bash
ASSISTANT_GATEWAY_REMOTE_ADDRESS=100.86.154.22
ASSISTANT_GATEWAY_REMOTE_BROWSER_DEVICES=nPc1nAnbd411CNTRL
ASSISTANT_GATEWAY_REMOTE_HOST_NAMES=laptop.tail2e4542.ts.net
ASSISTANT_GATEWAY_REMOTE_TLS_CERTIFICATE=/home/you/laptop.tail2e4542.ts.net.crt
ASSISTANT_GATEWAY_REMOTE_TLS_KEY=/home/you/laptop.tail2e4542.ts.net.key
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
- **`ASSISTANT_GATEWAY_REMOTE_HOST_NAMES`** is the name you type on the phone.
  It used to be a convenience and is not one any more: the gateway will not
  start unless it is set and **every** name in it is one the certificate
  carries. An uncovered name is one the gateway would answer to and no browser
  could ever reach, so it is refused at start naming the element rather than
  discovered as a warning on the phone (ADR-0202 §6). The gateway still resolves
  nothing — a name here is accepted as a `Host` header value and is never used
  as a destination.
- **`ASSISTANT_GATEWAY_REMOTE_TLS_CERTIFICATE`** and
  **`ASSISTANT_GATEWAY_REMOTE_TLS_KEY`** are the two files step 3 wrote,
  absolute paths. They are set together with the address and unset together with
  it: a certificate with no key, a key with no certificate, a pair with the
  listener off, or the listener on with no pair are each refused when the
  settings load. There is no third setting — no port of its own, no switch for
  plain HTTP, and no renewal interval, because renewal is your act (ADR-0202
  §8).

Set the address without the pair and the load says so, which is the mistake an
owner upgrading from an older deployment makes first:

```text
Error: invalid configuration: 1 validation error for Settings
  Value error, gateway_remote_address='100.86.154.22' is set, so the remote
  browser listener serves HTTPS and nothing else — there is no setting that
  makes it serve plain HTTP and no fallback to it (ADR-0202 §2). Set
  gateway_remote_tls_certificate and gateway_remote_tls_key to the pair your
  overlay obtained for this machine's own overlay name, or unset
  gateway_remote_address to serve browsers over the loopback listener alone
```

The two lists are likewise **refused at load while the address is unset**, rather
than being ignored:

```text
Error: invalid configuration: 1 validation error for Settings
  Value error, gateway_remote_browser_devices=['nPc1nAnbd411CNTRL'] is set while
  gateway_remote_address is unset, so the remote browser listener it grants a
  permission on is off and nothing would ever read it (ADR-0174 §8). Set
  gateway_remote_address to the overlay address the gateway should serve
  browsers on, or unset gateway_remote_browser_devices
```

## 5. Restart the gateway, and read what it prints

Stop the gateway with `Ctrl-C` and start it again. It now discloses **every**
origin it can be reached at:

```text
Assistant gateway listening on http://127.0.0.1:8422,
https://100.86.154.22:8422, https://laptop.tail2e4542.ts.net:8422
Bootstrap value (good once, and only for this gateway process):
pDSYe-a4xKAcwzG_nJMU0vvgpQ1fN0cTHfQCqNwDOGc
Live sessions: 0 of 8. For another value: kill -SIGUSR1 3941204
```

Copy the `https://` origin with the **name** in it. That is what you type on the
phone, and it is the whole reason this line exists — you should not have to
reassemble it from two settings.

Just below it, the gateway says what it bound the second listener with:

```text
2026-08-27T09:14:22Z [info    ] gateway.remote_listening
certificate_expires=2026-11-25T09:14:22+00:00
certificate_names=['laptop.tail2e4542.ts.net'] listed_devices=1
origins=['https://100.86.154.22:8422', 'https://laptop.tail2e4542.ts.net:8422']
scheme=https
```

Three facts and no more: the scheme, the name the certificate carries, and when
it stops being valid. **The expiry is the whole of the renewal story.** Nothing
watches the files and nothing warns you later, so this line at every start is
where you find out how long you have — and `tailscale cert` again, then a
restart, is the fix. Let it lapse and the gateway will not start at all, which is
the cost §2 accepted on purpose (ADR-0202 §4, §5).

If it does not start, the reason is on that same stream, in a sentence naming the
setting and the condition — the file is missing, another user can write to it,
the key does not match the certificate, the certificate is out of date, or it
does not carry a name you listed.

## 6. Open it on the phone — and type the `https://`

Type the origin into the phone's browser **including the scheme**:

```text
https://laptop.tail2e4542.ts.net:8422
```

Two reasons the scheme is worth typing rather than leaving to the browser. A bare
`laptop.tail2e4542.ts.net:8422` in a phone address bar is as likely to be treated
as a search as an address. And `http://` gets nothing at all: this listener
speaks HTTPS and nothing else, it does not fall back, and it serves no redirect
from `http://` either — a redirect would need the plain-HTTP listener the
decision refuses (ADR-0202 §2).

**Use the name, not the address.** The numeric origin is still one the gateway
answers to, and in practice you can no longer reach it: your certificate names
the machine, the address is not that name, and the browser refuses the mismatch
before a request is ever made. That is not a rule the gateway enforces — it never
sees the request — and it is the same instruction the page gave before for a
different reason: pick one authority and stay on it. A session belongs to the
origin it was minted at, so a session started at one does not admit at the other.

## 7. Mint a value for the phone, and paste it

Same panel, same field, same rule: good once, and good for ten minutes.

The value the gateway printed at start has almost certainly gone to the laptop's
browser already, and it is spent. So mint another one — at the **laptop**, in the
terminal running the gateway or any other on that machine, as the user that
started it:

```bash
kill -SIGUSR1 3941204
```

The process id is on the last line of every disclosure the gateway makes — and
that line is also the gateway's offer to do this at all. A gateway that could not
install the act prints no such line and says so at start; sending the signal to
one of those can stop it and end every session with it, so if the line is absent,
do not. [`first-run.md`](first-run.md)'s *When it does not work* is that case.

A fresh value appears on the gateway's own terminal:

```text
Assistant gateway listening on http://127.0.0.1:8422,
https://100.86.154.22:8422, https://laptop.tail2e4542.ts.net:8422
Bootstrap value (good once, and only for this gateway process):
IznwmhTUYUKp04I8Z_BfM8_tMFKYaCrDZqcFm_wCNGQ
Live sessions: 1 of 8. For another value: kill -SIGUSR1 3941204
```

Nothing restarted and the laptop is still logged in — `Live sessions: 1 of 8` is
its session, counted against `ASSISTANT_GATEWAY_MAX_SESSIONS`. That count is
information rather than a refusal: the gateway mints whatever it is, and it is
the *exchange* that is refused once the table is full. Paste the new value on the
phone and both devices hold a session at once (ADR-0182 §1, §2).

Ten minutes is the window between reading the value off the laptop and the phone
spending it (`ASSISTANT_GATEWAY_BOOTSTRAP_TTL`) — generous for walking across a
room, and the reason a value left in your scrollback is not a lasting liability.
If it runs out, send the signal again; the value it replaces stops working the
moment the new one is printed.

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
Your bootstrap value is untouched and still works — it was not read or spent, so
it admits for the rest of its ten minutes.

**The phone cannot reach the address at all.** That is the overlay, not the
gateway. `tailscale status` on the phone, and check the laptop is not asleep.

**The gateway prints only the loopback origin.** `ASSISTANT_GATEWAY_REMOTE_ADDRESS`
did not load. Check you edited the `.env` in the directory you start the gateway
from, and that no environment variable of the same name is overriding it.

**The gateway does not start at all, and names a file.** That is ADR-0202 §2
working: a remote listener configured on serves HTTPS or the gateway stays down.
The sentence says which condition failed and on which path — the file is missing
or unreadable; it is owned by another user; its mode lets group or other read the
key or write the certificate; it sits under a directory anyone can replace it
through; it is not a certificate this system can parse; the key does not belong
to the certificate; the certificate is expired or not yet valid; or it does not
carry every name in `ASSISTANT_GATEWAY_REMOTE_HOST_NAMES`. The last two are the
ones you will meet: run `tailscale cert` again, `chmod 0600` the key, and
restart.

**The phone shows a certificate warning.** You are at an authority the
certificate does not name — almost always the numeric address rather than the
name. Type the `https://` origin with the name in it, from step 5's line. Do not
click through the warning: the browser's refusal is the mechanism this whole page
exists to obtain, and overruling it gives back exactly what the certificate
bought.

**You want the local browser back and the certificate has lapsed.** Unset
`ASSISTANT_GATEWAY_REMOTE_ADDRESS` together with both TLS paths and restart. The
gateway then binds the loopback listener alone, exactly as it did before this
page. It is a deliberate act rather than something that happens quietly, which is
the point (ADR-0202 §2).
