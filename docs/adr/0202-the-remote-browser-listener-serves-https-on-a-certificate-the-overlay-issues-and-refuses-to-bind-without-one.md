# 202. The remote browser listener serves HTTPS on a certificate the overlay issues, and refuses to bind without one

- Status: Proposed
- Date: 2026-08-27

- **This is the scheme decision ADR-0174 §7 demanded and §11 deferred** (#1668).
  §7 ruled that "a lane that finds the milestone-14 browser surface requires
  [a secure context] … **stops** and owes a ratified decision on the scheme", and
  §11 listed the trigger that fires it: "when voice's first rung (#1318) asks for
  microphone capture in the browser, which is such a capability". #1668 records
  the trigger firing — `track:voice` milestone 19's exit test is *the owner holds
  push-to-talk in a browser on another device*, and `getUserMedia` is one of the
  five capabilities §7 names. The owner ruled option 1 on 2026-08-27: ratify the
  scheme, and milestone 19's exit test stands as written.
- **No implementation lands with it.** No `src/`, no `tests/`.
- **It decides no `core/protocols.py` and no `core/types.py` surface** (§9), so
  golden rule 5 is not triggered. It adds two `Settings` fields (§8), which are
  contract surface in ADR-0054's sense — the position ADR-0084 §3 was in for its
  four transport figures, ADR-0168 §8 for its ten and ADR-0174 §8 for its three.
- **It partially supersedes two ADRs and writes the scope text for both records**
  (§10): **ADR-0004 §3's keyring clause and §7's gating clause**, each only as
  each reaches the remote browser listener's TLS key material, and **ADR-0174
  §7's plain-HTTP clause** — the clause this decision exists to replace — together
  with **one sentence of ADR-0174 §8**, its empty default for the remote host-name
  list, which §6 turns into a refusal to start, and **one limb of ADR-0174 §6's
  delegation clause**, its claim that §8 is the single statement of when that list
  is refused. §10 applies ADR-0070 §1's test
  clause by clause to every other ADR a reader might expect this to falsify and
  finds no further record owed.
- **The records on those two ADRs' own header lines are the implementing lane's
  first act**, not this change's. ADR-0070 §1 permits the `Status` edit that
  records "a supersession that has landed", and one lands when this ADR merges;
  §10 writes the two pairs verbatim so the lane copies rather than composes them.
- **Its required review set is adversarial *and* architecture.** It replaces a
  clause of ADR-0004 — the data-handling decision — for a Tier 0 value, and it
  decides the transport of a ratified egress boundary. ADR-0172 took both lenses
  for the first of those and ADR-0174 for the second.
- **One consequence is named up front because it is a new disclosure.** The
  certificate comes from a publicly trusted authority, obtained through the
  overlay's control plane, so the gateway machine's overlay name becomes **public**
  where it was previously held by the overlay's operator alone. §4 states that
  delta and the issuance event beside it, accepts both in ADR-0124 §3's own terms,
  and names the one exit.

## Context

### What fired the deferral, and what it does not block

`track:voice`'s milestone 19 is push-to-talk in the browser, and `docs/roadmap.md`
states its exit test as *the owner holds push-to-talk in a browser on another
device, asks aloud about their own life, and hears an answer drawing on
accumulated memory*. A browser on another device reaches the gateway through the
remote browser listener ADR-0174 decided, that listener speaks plain HTTP, and a
page served over `http://` from an address that is not loopback is not a
"potentially trustworthy origin" — so the browser withholds the microphone.

#1668 records what that does and does not block, and the boundary is worth
keeping in view because it is what makes this a scheme decision and not a
milestone decision. Everything hub-side — the speech Protocols, their triads and
the wire carriage the milestone-19 contract ADR decides — is browser-agnostic and
was never blocked. Push-to-talk in a browser on the gateway's **own** machine was
never blocked either: a loopback origin is potentially trustworthy for free, which
is ADR-0174 §7's own observation that "loopback got the classification for free and
nobody had to notice". What is blocked is exactly one thing, and it is the words
*on another device* in the exit test.

### What ADR-0174 §7 already settled, and what it left open

§7 settled three things and this ADR takes all three as its starting point rather
than reopening them.

It settled that **the boundary's own confidentiality is not what is missing**: §2
requires the payload encrypted end to end between the two devices with no third
party holding a key, and the overlay supplies that for the browser leg as it does
for the hub leg. What is missing is that "the browser does not know it".

It settled that **the two properties may never be conflated**: "no lane may read
§2's end-to-end encryption as supplying a secure context in a browser". That
clause is untouched here, and this ADR supplies the classification by a different
means rather than by re-reading §2.

And it examined **three routes and took none**, in words this decision is bound
by. An overlay-issued certificate for a MagicDNS name "is the workable one, and it
costs an operating act with a control-plane feature behind it, a dependence on
names #912's posture is careful about, and a renewal story — a real decision, with
real conditions, that wants the surface lane's requirement in hand before it is
made". A self-signed certificate "trains the owner to click through a warning,
which is a habit worth more than the capability". Terminating TLS in an overlay
"serve" feature "is refused by §2 on the mechanical ground that it destroys the
peer identity §3 requires".

The surface lane's requirement is now in hand: it is microphone capture, and it is
#1668. What was left open is the operating act, the key material, the renewal and
the name — the four conditions §7 named. This ADR decides those four and nothing
else.

### What the tree holds, checked rather than remembered

`core/config.py` carries ADR-0174 §8's three fields today —
`gateway_remote_address`, `gateway_remote_browser_devices` and
`gateway_remote_host_names` — with the address nullable because it is the switch,
and with either list being non-empty while the address is unset refused at
settings load. The gateway itself is `src/ai_assistant/interfaces/gateway/`, and
`server.py` is where a listener is bound.

`docs/guide/phone.md` is the operating recipe an owner follows today, and its
step 5 is the sentence this decision changes: "Type the origin into the phone's
browser **including the scheme**", followed by `http://100.86.154.22:8422` and the
explanation that "`https://` does not work here and is not meant to: this listener
speaks plain HTTP". The same page already tells an owner that two things are
unavailable over this listener for want of a secure context, "operating-system
notifications … and **microphone capture**", and names ADR-0174 §7 as the reason.
That page is a consequence of this decision rather than a part of it (§10).

The same page also establishes that **the MagicDNS name already works**: "If you
configured `ASSISTANT_GATEWAY_REMOTE_HOST_NAMES`, the MagicDNS origin works
identically and is much easier to type." An owner's browser is therefore already
resolving that name to reach this gateway, under a ratified clause, before this
ADR exists. §6 turns on that fact.

`wire/custody.py` holds the predicate this system already applies to "a path
trusted rather than authenticated" — the property "that no untrusted user can
replace the entry that is about to be opened" — shared by the hub's data
directory and by both ends' overlay agent sockets. §3 makes the key file a fourth
such path rather than inventing a fourth rule for it.

### Why the browser's classification is the whole of the problem

Nothing about the wire changes when a certificate arrives. The bytes were already
encrypted end to end by the overlay and they still will be; a browser that speaks
HTTPS over an overlay tunnel encrypts the same payload twice. What the certificate
buys is a **classification**: the browser can now name the origin as trustworthy,
and the capability gates open.

That is an uncomfortable thing to spend an operating act on, and it is worth
stating plainly rather than dressing up, because it is also the reason the
self-signed route is refused. If the point were confidentiality, a self-signed
certificate would deliver it exactly as well and the warning would be a nuisance.
The point is that the browser's own trust decision is the mechanism, so a route
that reaches the capability by training the owner to overrule that decision has
spent the mechanism to buy its output.

## Decision

### 1. The scheme is a certificate the overlay obtains for the machine's own overlay name

> **Normative.** The gateway's remote browser listener serves **HTTPS**, and
> terminates TLS in the gateway's own process. Its certificate is one the
> **overlay obtains for a name the overlay assigns to the machine that runs the
> gateway**, and its private key is generated on that machine and never leaves it.

> **Normative.** That certificate chains to a **publicly trusted** authority — one
> the browsing device already trusts out of the box, with nothing installed on that
> device for this purpose and nothing for the owner to overrule. A chain the
> browser does not already trust does **not** satisfy this ADR, whoever operates
> it: it produces a warning instead of a secure context, which makes it the
> self-signed route under another name and refuses with it. A chain the browsing
> device trusts because some **other party** administers a root on it — an
> employer's device-management root, say — does not satisfy it either: it lets that
> party mint a certificate for the gateway's own name and stand between the owner
> and their assistant, with nothing recording that it did.

> **Normative.** No other issuance route is authorised. A **self-signed**
> certificate is refused; a certificate for a name outside the overlay, from a
> certificate authority the overlay does not operate or delegate to, is refused;
> and TLS terminated anywhere but the gateway's own process — a proxy, a tunnel,
> or an overlay "serve" feature — is refused. ADR-0174 §2's prohibition on placing
> any of those in front of either listener is applied unchanged and is not lifted
> by this ADR.

> **Normative.** The clause above binds **the owner's provisioning act and the
> design of any lane**, and it is not a start-time check. No clause of this ADR
> requires the gateway to determine a certificate's issuer, its provenance, or
> whether the name it carries is one the overlay assigned; the gateway checks what
> §8 enumerates and nothing else, and a certificate that passes those checks is
> bound whatever its origin.

> **Normative.** Nothing in this ADR is conditioned on Tailscale. ADR-0124 §2's
> acceptance is of an overlay rather than of a vendor, and an overlay satisfies
> this ADR when it satisfies ADR-0124 §2 and issues, for a name it assigns, a
> certificate meeting the trust requirement above. Moving to such an overlay
> reopens no clause of this ADR; moving to one whose issuance does not meet that
> requirement is not a move this ADR permits.

**The vendor's instance, named once so the clause is checkable against something
real.** Tailscale's `tailscale cert` obtains a certificate for the machine's
MagicDNS name — `laptop.tailnet-name.ts.net` — from a public certificate
authority, using the control plane to prove the name, and writes the certificate
and the private key as files on the machine that asked. That is the worked case of
the clause above, and it is named the way ADR-0124 §2 named Tailscale: as the
first implementation of a property, not as the property. **"The overlay issues" in
this ADR's title names that act** — the overlay proves the name and hands back the
certificate — and the clauses above say the rest: the signature comes from a
publicly trusted authority, and the key is the machine's own.

**The trust requirement is what makes the vendor-neutral clause mean anything, and
architecture review was right that without it the clause was empty.** An earlier
draft let any ADR-0124-compliant overlay that "issues a certificate for a name it
assigns" satisfy this ADR — which an overlay running its own private authority
does, while the browser shows a warning and withholds the microphone exactly as
before. That is the self-signed outcome reached by a longer route, and it would
have made this decision buy nothing. Stating the requirement as a property of the
**chain the browsing device already trusts** keeps the neutrality that matters —
no vendor, no named authority, no issuance API in the clause — while ruling out
the routes that do not deliver the classification this ADR exists to obtain.

**§4's disclosure follows from this clause rather than sitting beside it.**
Requiring a chain the phone already trusts is what puts the name in front of a
public authority — and, because the major browsers require certificate
transparency of publicly trusted certificates, into a public log. The requirement
and the disclosure are one decision taken twice, and §4 accepts the second half
knowing it is the price of the first.

**A second admitted root was drafted and then withdrawn, and the reason is worth
recording rather than quietly dropping.** An intermediate draft also admitted a
root the *owner* administers, on the ground that a device already trusting one
gets the secure context with nothing published anywhere — a strictly better
privacy outcome that a decision should not forbid. It did not survive its own
consequences. It split the issuance requirement from the trust requirement, since
an owner's authority issuing the leaf is not the overlay obtaining it; it split
§4's disclosure account in two; and review found a fresh contradiction in each of
the two rounds that followed. Against that, its beneficiary is an owner whose
browsing device *already* trusts an authority they run and who did not install it
for this — and installing one for this is what the clause above refuses. **One
route, stated once, is the better decision**, and an owner who really is in that
position has the ordinary remedy: a superseding ADR, on evidence this one does not
have.

**Why the other two stay refused, in ADR-0174 §7's own words rather than
paraphrased.** A self-signed certificate "trains the owner to click through a
warning, which is a habit worth more than the capability" — and the section above
says why that is not merely a preference: the browser's trust decision is the
mechanism being bought, so a route that teaches the owner to overrule it has spent
what it was buying. Terminating TLS in an overlay "serve" feature "is refused by
§2 on the mechanical ground that it destroys the peer identity §3 requires": a
connection arriving through a terminating proxy is a connection *from the proxy*,
so the gateway's `whois` on its peer address learns about the proxy and not about
the browsing device, and ADR-0174 §4's admission has nothing left to compare
against its list. Both refusals are ADR-0174's, restated here because this is the
decision that could have overturned them and does not.

**A ruling the gateway cannot mechanically enforce is still a ruling, and this
corpus already keeps one on this listener.** ADR-0174 §2 forbids an
operator-configured proxy, port forward, tunnel or "serve" feature in front of the
loopback listener, and nothing in the gateway detects one; ADR-0168 §2's
prohibition is "reinforced rather than lifted" all the same. The refusals above
are of that kind, and saying so is what keeps a lane from inferring a check the
gateway cannot make. **The tree is why it cannot make it**: the overlay agent's
surface here is a stable identity and a set of addresses, and `service/overlay.py`
records in terms that there is "deliberately no fallback to a name", because a
value that can be renamed is the wrong thing to bind an identity to. So a gateway
holding a valid certificate and key for a name in `gateway_remote_host_names` has
no attested way to learn whether that name is the overlay's or the owner's own
domain, and this ADR does not pretend otherwise: it rules which certificate the
owner installs, and §8 rules what the gateway checks about whatever was installed.

**Narrowing the decision to one verifiable overlay profile is the other way to
close that gap, and it is refused.** It would make the refusals checkable by
naming a vendor's issuance API — and ADR-0124 §2's acceptance "is of an overlay
rather than of a vendor", a posture ADR-0174 §2 restates for this listener in
terms. Buying enforceability with vendor-conditioning would cost more than the gap
it closes, and the gap it closes is one the owner's own act already stands in.

**The public-CA refusal is new and it is narrow.** ADR-0174 §7 did not name it,
because it was surveying routes to a secure context rather than bounding them.
What the clause refuses is a certificate for a name that is not the overlay's —
the owner's own domain pointed at the gateway, say. That route works, and it is
refused because it is the first half of a public door: it puts a name the owner
controls in front of a listener, and the only thing still keeping the listener off
the internet is ADR-0174 §2's bind clause. Keeping the name inside the overlay
keeps the two halves from drifting apart one lane at a time. Nothing here forecloses
a public door; it says that a public door is its own decision and not a
side-effect of this one.

### 2. HTTPS is mandatory on that listener, and there is no plain-HTTP fallback

> **Normative.** A configured remote browser listener serves HTTPS and nothing
> else. No setting makes it serve plain HTTP, and the gateway may not fall back to
> plain HTTP on any condition — an absent file, an unreadable file, an expired
> certificate, or a failed handshake.

> **Normative.** A gateway whose remote browser listener is configured on and
> whose certificate or key is absent, unreadable, unusable, mismatched, or outside
> the certificate's validity period at that moment **does not start, and reports
> why**. It does not bind the loopback
> listener alone and continue, and it does not bind the remote listener without
> TLS.

> **Normative.** No plain-HTTP redirect is served on the remote listener's address
> or port. The clause above admits no exception for one, because serving a
> redirect would require the plain-HTTP listener it refuses.

> **Normative.** ADR-0168 §2's **loopback** listener is untouched. It speaks plain
> HTTP, it is bound whether or not the remote listener is, and no clause of this
> ADR adds a certificate, a key or a scheme requirement to it.

**Mandatory rather than optional is the whole of what makes this worth a
decision.** An option beside plain HTTP is the arrangement that produces the
failure #1668 was filed about: a listener that mostly works, a page that mostly
renders, and one capability that silently is not there — "it works except the
mic". A browser gives no legible account of *why* it withheld the microphone, so
the owner's evidence is a button that does nothing. Making the scheme a property
of the listener rather than a setting means the failure, when it happens, happens
at the one place a gateway can explain itself: start-up, on the owner's own
terminal.

**Refusing to start rather than degrading is ADR-0083's ruling 4 arriving through
the settings file, and ADR-0174 §8 already took this decision once.** An owner who
configured a remote listener and got a loopback-only gateway has "a configuration
that says something the running process does not do", which is the failure
ADR-0174 §8 refused for its two lists and refused *by name*. The shape of the
refusal is ADR-0168 §5's: "A gateway that cannot disclose its bootstrap value does
not start, and reports why."

**Refusing the redirect is the same refusal one step later, and it costs the owner
one character.** A gateway that answered `http://` on that address with a redirect
would be a plain-HTTP listener on the port — one that answers before any
certificate is involved, and one a future lane could grow. `docs/guide/phone.md`
already teaches typing the scheme, for a reason that survives the inversion: "a
bare `100.86.154.22:8422` in a phone address bar is as likely to be treated as a
search as an address". What that page has to stop saying is the sentence after
it — that "`https://` does not work here and is not meant to".

**A gateway that does not start binds no loopback listener either, and that is
ADR-0174's own arrangement rather than a change to it.** §2's clause that "that
loopback listener is bound whether or not this one is" says the loopback listener
does not depend on the remote one being **configured on** — a gateway with no
remote configuration binds it, which is the sentence's subject. It is not a
promise that the gateway starts under every remote *mis*configuration, and
ADR-0174 is the ADR that proves it: its own §2 refuses a wildcard, loopback or
publicly-routable `gateway_remote_address` "at load rather than bound", and its
own §8 has the "**gateway refuse[] at start**, before it binds or discloses a
bootstrap value" an overlay identity over the byte bound. Both outcomes are a
process that does not run, and therefore a loopback listener that is not bound.
The clause above adds a third condition of exactly that kind. Architecture review
raised this on its first round, reading §2's clause as a loopback-availability
guarantee; §10 records why the test comes out at no supersession rather than
writing a record ADR-0082 §1 would make wrong.

**The residual is stated rather than closed: an expired certificate takes the
gateway down, including its loopback listener.** An owner whose certificate lapsed
and who wants the local browser back turns the remote listener off — unsetting
`gateway_remote_address` together with §8's two paths, which §8 refuses to see
parted — and restarts. It is an explicit act, which is the point. The alternative, binding
loopback and continuing quietly, is the same silent degradation in a different
place, and it would leave the owner's phone with a page that will not load and no
statement anywhere about why. §5's disclosure exists so that this residual is met
before it bites rather than after.

### 3. The key material is a file on the gateway's own machine, and it is not in the keyring

> **Normative.** The certificate and the private key are **files on the gateway's
> own machine**, named by §8's two paths. The gateway **reads** them and does
> nothing else with them: it never writes them, never copies them, never transmits
> them, and never places either — or any part of the key — in a log record, in an
> error, in a response body, or in any disclosure §5 makes.

> **Normative.** The private key is Tier 0 under ADR-0004 §1. ADR-0004 §3's
> keyring clause is superseded **only** for this class — the **remote browser
> listener's TLS key material**, which is exactly the private key the overlay
> issued for the gateway machine's overlay name together with the certificate that
> accompanies it — and for nothing else. The class is closed. No lane may cite this
> ADR to place any other Tier 0 value outside the OS keyring, and admitting a
> further kind takes its own ratified decision, however closely it resembles this
> one.

> **Normative.** The certificate is **not** a secret and is not in that class for
> its own sake: it is public by construction (§4). It is named in the class only so
> that the pair is provisioned, renewed and refused together.

> **Normative.** The gateway refuses at start a key file readable or writable by
> any user other than the one the gateway runs as, and refuses a certificate or
> key path failing the custody conditions `wire/custody.py` already owns for a
> path trusted rather than authenticated. It reports which condition failed and on
> which path.

**Why the keyring is not available here, checked against ADR-0125 rather than
assumed.** ADR-0125 §2 closes `SecretScope` at exactly three members — `PROVIDER`,
`INTEGRATION` and `ENROLMENT` — and rules that "a fourth consumer needs a fourth
member, which is `core` surface and therefore its own ADR". A TLS key is none of
the three. ADR-0125 §8 then rules that `interfaces` holds neither face of the seam
and that no subsystem "may acquire one without the ADR §2 requires for a fourth
scope"; the gateway is `interfaces/gateway/`. So the keyring route costs a
`core/types.py` change and an amendment to §8's consumer boundary — two contract
decisions, ahead of any TLS code, under golden rule 5 — before it can begin.

**And it would buy nothing, which is the part that matters more than the cost.**
The key is not this system's to mint: the overlay agent generates it on this
machine, writes it, and rewrites it on every renewal. Routing it through the
keyring would mean the gateway reading a file the agent owns, copying a Tier 0
value into a second durable store, and rewriting that copy every renewal or
serving a stale one. That is strictly worse than reading the file the agent
already keeps — a second copy of a secret, kept in sync by a mechanism nobody
asked for.

**ADR-0125 §8's file-read prohibition is examined and found unengaged, because it
carries its own scope.** It reads: "No lane may add a new path to a Tier 0
credential — an environment read, a file read, or a direct keyring import — **for
any secret this seam can hold**." The seam can hold only §2's three scopes, this
key is in none of them, and this ADR adds no fourth scope. So no clause of
ADR-0125 becomes false or over-wide and no record is owed against it (§10). That
clause is quoted rather than passed over precisely because a reader who stopped at
its first half would conclude the opposite.

**ADR-0172's exemption is not cited, not widened, and not relied on.** ADR-0172 §3
rules that "no lane may cite this clause toward a fourth exemption. A further Tier
0 access that cannot be gated by `permissions/` owes its own ratified decision, on
its own argument, however closely it resembles this one." This is that decision and
that argument, made in §10 on its own terms; if the argument is rejected this
exemption falls rather than surviving on ADR-0172's, on ADR-0124 §6's or on
ADR-0126 §11's.

**Owner-only permissions and the custody walk are the same discipline ADR-0004 §4
applies to the memory database** — "owner-only file permissions (`0600`) in the
user's data directory" — applied to key material rather than to a store, and the
walk is the one `wire/custody.py` already performs rather than a fourth
restatement of it. ADR-0084 §1's caution comes with it unchanged: a filesystem
walk "can be wrong — a bind mount, an ACL, a symlinked ancestor", so this is
defence in depth and not the thing that protects the key. What protects the key is
that it is on the owner's own machine, owned by the owner's own user.

### 4. Provisioning and renewal are operating acts the owner performs, and the disclosure they cause is accepted

> **Normative.** Obtaining the certificate is an **operating act the owner performs
> on the gateway's own machine**, in the shape ADR-0124 §6 gives enrolment. No
> component of this system obtains, requests, renews or revokes a certificate, and
> none invokes the overlay agent to do so.

> **Normative.** ADR-0124 §3's clause that "no component of this system transmits
> to an overlay control plane, and the overlay agent is not imported by, embedded
> in, linked into or launched by `ai_assistant`" is applied **unchanged**. The
> gateway reads two files the owner placed, exactly as it binds an address the
> agent provides and reads the agent over a local interface.

> **Normative.** Renewal is likewise the owner's act, and a renewed certificate
> takes effect when the gateway is **next started**. The gateway reads the
> certificate and the key when it binds and does not re-read them while it runs; no
> clause of this ADR obliges a reload, and no lane may present the gateway as
> renewing, watching or reloading anything.

> **Normative.** The certificate is obtained for a name the overlay assigns, so the
> overlay's **control plane learns that one was obtained** for that machine and
> when. Where that control plane is a third party's, that is a disclosure beyond
> ADR-0124 §3's enumeration — which names what the operator holds about devices and
> networks and does not name an issuance event — and it is **accepted** here rather
> than read into §3's acceptance.

> **Normative.** §1's publicly trusted authority then makes the gateway machine's
> overlay name **public**, in the certificate itself and in the transparency logs
> such an authority publishes to. That is a second disclosure and it too is
> **accepted**.

> **Normative.** Both are accepted on the same terms ADR-0124 §3 accepted the
> coordination metadata: each is the owner's act, each is bounded and enumerable,
> and each discloses a name and an instant and nothing else — no request, no
> response, no byte of the store, and no address that is reachable from the public
> internet.

**The delta is smaller than it first looks, and naming it exactly is what makes it
acceptable.** ADR-0124 §3 already has the overlay's operator holding "each
device's name, platform and public key", and the times at which each device is
online. The name is therefore not newly known to the operator, and neither is the
fact that the machine was doing something at a given instant; what §3's
enumeration does not name is an **issuance**, and what is new beyond that is that
the name goes **public** rather than staying with that one party. Adversarial
review found the first half while an intermediate draft still admitted a second
root — an owner running someone else's control plane and their own authority still
tells that operator a certificate was obtained — and the point outlived the draft,
which is why the two disclosures are stated separately above. An overlay name
derived from the owner's account is the case where the second matters most, and an
owner for whom it matters has the vendor's own remedy: the tailnet name is theirs
to choose.

**What the public name does not give anyone is a way in.** The listener binds an
overlay address under ADR-0174 §2, unchanged; the name resolves outside the
overlay, if it resolves at all, to an address that is not routable from the public
internet; ADR-0174 §3 refuses any connection whose overlay identity cannot be
obtained, before anything is served; and ADR-0174 §4 admits a bootstrap exchange
only from a device the owner listed. A reader of a public log learns that a
machine by that name exists. Every door is exactly where it was.

**ADR-0124 §3's revisit condition is what points here, and it is honoured rather
than lawyered past.** §3 says "the enumeration is the thing that was accepted; a
disclosure beyond it was not", and this is a disclosure beyond it. It is therefore
accepted **here**, in this ADR, by an owner act this ADR requires — not read into
§3's acceptance. Under ADR-0082 §1 that makes it a stacked addition recorded in
the ADR that makes it and nowhere else, and §10 says so.

**ADR-0124 §3's residency finding is untouched, and the clause that guards it is
the reason.** §3 rules that its finding "rests on this system transmitting nothing
to a control plane. If any component of this system ever does, the residency
question becomes live". No component of this system does: the transmitter is the
overlay agent, run by the owner, as it already is for every other thing that agent
does. This is precisely why the first clause of this section forbids the gateway to
invoke it — the convenience of a gateway that provisions its own certificate would
have cost ADR-0004 §2's residency question, and it is not for sale at that price.

**The one exit is the name itself, and the two that look like exits are not.** An
overlay name that says nothing about the owner discloses nothing about them, and
choosing it costs an operating act they are performing anyway. A control plane the
owner hosts removes the vendor from the issuance path but **not** the public
authority from it, because §1's requirement is a fact about the browsing device
and not about who runs the overlay: an owner who self-hosts still ends up in a
public log. And a privately trusted root, which would remove the log entirely, is
refused by §1 — installing one for this purpose is the self-signed hazard wearing
a better hat, and relying on one somebody else installed hands that party the
gateway's own name. **Revisit when** the trust requirement can be met some third
way, or when what an overlay's issuance discloses stops matching this section.

### 5. What the gateway discloses when it binds, and what that disclosure is not

> **Normative.** When the remote browser listener binds, the gateway discloses on
> its own standard output, beside the address it bound: that the listener speaks
> HTTPS, the name the certificate carries, and the instant the certificate's
> validity ends. It discloses nothing of the private key.

> **Normative.** That disclosure carries **Tier 2 facts only** — a name of the
> gateway's own machine, an instant, and a scheme. ADR-0174 §3 classifies an
> overlay identity as a Tier 2 fact about a device, and this is the gateway's own.

> **Normative.** The disclosure is **not** a record under ADR-0168 §6. §6's
> enumeration governs records about **requests** — admission decisions — and a
> start-up disclosure is not one, exactly as ADR-0168 §5's disclosure of the
> bootstrap value is not one. No clause of ADR-0168 §6 is widened, and its
> enumeration gains no member here.

> **Normative.** A **failed TLS handshake** produces no ADR-0168 §6 record either.
> A connection that yields no request is not a request refused, and no lane may
> add a record class, a condition or a counter for it under that section.

> **Normative.** ADR-0174 §3's overlay-identity check runs on the connection
> **before** the TLS handshake, so a connection whose overlay identity cannot be
> obtained is closed without the certificate being presented.

**Neither clause about records adds anything to ADR-0168 §6; both apply it.** §6
rules that "every request the gateway receives is of exactly one class, out of
four", and that a refusal record names one class and one condition. A connection
that never yields a request has no class to be of, so §6 already excludes it, and
the clause above states the application rather than making an exception to it. The
reason to state it at all is that a TLS listener is the first thing this gateway
has that can fail *before* a request exists, and a lane looking at §6's four
classes would otherwise have to decide whether to invent a fifth.

**Both bounds, not just the far one, and the near one is not hypothetical.**
Adversarial review found the asymmetry on its sixth round under this lane: §8 had
enumerated expiry alone, so a certificate whose validity had not begun passed every
check and bound a listener every browser rejects — §2's "unusable" reached by a
route §8 did not test for. A certificate issued against a clock the gateway's
machine disagrees with is the ordinary way to arrive there, and it is the one case
where the gateway's refusal is more useful than the browser's, because the gateway
can say which bound failed and the browser cannot.

**The expiry instant is the renewal story's whole mechanism, and that is
deliberate.** §4 puts renewal in the owner's hands and refuses to have the gateway
watch anything; what makes that workable rather than a trap is that every start
tells the owner how long they have. It costs one line on a stream the owner
already reads — `docs/guide/phone.md`'s step 4 is literally "Restart the gateway,
and read what it prints" — and it needs no timer, no state and no second
mechanism.

**Ordering the identity check before the handshake buys little and costs nothing,
and both halves are stated.** The certificate is public (§4), so declining to
present it to an unidentified peer protects nothing of consequence. What it does
is keep ADR-0174 §3's "before serving anything" at its strongest reading rather
than leaving a lane to decide whether a handshake counts as serving — a question
with no good answer that this clause removes. The check is on the peer's address
against the agent on this machine, which is the same call ADR-0174 §3 already
requires on every connection.

### 6. The browser addresses the name the certificate carries, and #912's posture is untouched

> **Normative.** The owner addresses the gateway at a name the certificate
> carries. That name is admitted by ADR-0174 §6 as an element of
> `gateway_remote_host_names`, under that section's rules unchanged: compared
> literally, admitted as a `Host` value, and never used as a destination.

> **Normative.** The gateway still **resolves nothing**. It binds the overlay
> address `gateway_remote_address` names, it compares `Host` literally against a
> set the owner configured, and it asks no resolver what any name means. This ADR
> adds no name-admission rule and no resolution step to ADR-0174 §6, and changes
> nothing about which `Host` values that section admits. The one sentence of §6 it
> reaches is that section's delegation of the field's **refusal** conditions to §8,
> superseded on the record §10 writes.

> **Normative.** The gateway refuses at start, and reports why, unless **every**
> element of `gateway_remote_host_names` is a name the configured certificate
> presents, and the list is non-empty. It names the elements that failed.

**Whose resolver participates is the question #912 is about, and the answer is
unchanged by this ADR.** #912 records that `wire.address.check_remote_address`
admits a literal address only for the **hub's destination**, on ADR-0124 §1's
ground that a client "obtains its destination from configuration and never from a
discovery mechanism" — so a name would make the destination "a fact about that
resolver rather than about the deployment". Nothing here touches a client, a hub
address or a destination. ADR-0174 §6 already drew the line for this listener — "a
`Host` header is not a destination … no resolver participates in what this gateway
does, and no name selects where anything is sent" — and this ADR sits entirely
inside it.

**The resolver that does participate is the browser's, and it was participating
before this decision.** `docs/guide/phone.md` tells an owner today that with
`gateway_remote_host_names` configured "the MagicDNS origin works identically and
is much easier to type". So the browser already resolves that name to reach this
gateway under a ratified clause. What this ADR adds is that the certificate now
**binds to** that name — it widens no resolver's participation, it constrains it.

**The mistyped-address residual ADR-0174 §3 stated is narrowed rather than
widened, which is worth saying because the opposite would be the expected cost.**
§3 accepted that "an owner who types the wrong overlay address reaches the wrong
device of their own overlay and is told nothing about it", and that a hostile
member occupying that address "serves its own look-alike page at its own
authority". Under this decision that member has no certificate for the owner's
name, so the browser refuses before a page renders — and the two clauses §3 relied
on to stop the phished value short of a session are still there behind it. What
remains is an owner who types a *different name of their own overlay* that also
holds a certificate, and reaches that device legitimately.

**Addressing the gateway by its literal overlay address stops working in
practice, and that is a consequence rather than a rule.** No gateway clause
changes: ADR-0174 §6 still admits the bound address as a `Host` value. What
happens is that the browser refuses the certificate's name mismatch before any
request exists, so the gateway never sees the `Host`. ADR-0174 §6's own
instruction already covers what an owner should do about it — "pick one authority
and stay on it" — and `docs/guide/phone.md` already says the same in the owner's
words.

**Refusing at start when the certificate does not name what the owner configured
turns a silent dead end into a sentence.** Without it the failure surfaces as a
phone that cannot load a page, from a gateway that started cleanly, for a reason
visible only in the certificate. It is ADR-0174 §8's own move — refuse at start
what only the running machine can decide — applied to the one new way this
configuration can be internally inconsistent.

**Every element rather than one, and adversarial review is why.** An earlier
draft asked only that *some* configured name match, which starts a gateway whose
list still carries an authority the certificate does not cover — a name ADR-0174
§6 dutifully admits as a `Host` value and no browser can ever reach, because it
refuses the certificate before the request exists. That is the same dead end the
clause exists to remove, hidden behind a list member that happens to work; a stale
name left over from a rename is the ordinary way to get one. Requiring every
element costs an owner nothing they can use, since an uncovered name is
unreachable either way, and it turns a page that will not load into a line at
start-up naming the element.

**This adds a condition to `gateway_remote_host_names`, and the clause it
falsifies is in ADR-0174 §6 rather than §8 — which is why §10 records a
supersession there rather than a stacked addition.** §6 of that ADR delegates the
field in terms: "`gateway_remote_host_names` is §8's field and §8 is the single
statement of what it holds, what its default is and **when it is refused**. This
section states only what the gateway does with it, and adds no condition on it."
Its second sentence stays true — ADR-0174 §6 gains no condition of its own — but
its first does not, because a refusal condition for that field now lives here,
outside §8. A reader holding only ADR-0174 §6 therefore reads that delegation more
widely than it now holds, and takes §8's conditions for the complete set. That is
ADR-0070 §1's second limb, and §10 scopes the record to that limb alone: what the
field holds is unchanged, and its default is still §8's to state — changed only by
the sentence of §8 recorded in the paragraph below.

**An earlier draft called this a stacked addition, and adversarial review was
right to block it.** The argument then was that every sentence of ADR-0174 §8 stays
true of a list this ADR additionally requires the certificate to cover. That is so,
and it answers the wrong clause. A stacked addition is what a clause carrying **no**
completeness claim earns — ADR-0182 §9's ground for ADR-0168 §8's settings table,
used again in §10 below for §8's own field list — and ADR-0174 §6 carries one in
terms. What §8 could not have spoken to is a certificate, because under ADR-0174
there was none; but §8's silence is not what owes the record. §6's claim of
completeness over §8 is.

**That refusal supersedes one sentence of ADR-0174 §8 and the record is owed, so
it is named here rather than absorbed** (§10). §8 says of
`gateway_remote_host_names` that "empty is the default, so a gateway configured on
serves the address it bound and nothing else". Under the clause above a gateway
configured on with an empty list does not serve the address it bound; it does not
start. A reader holding only §8 therefore acts differently, which is ADR-0070 §1's
first limb. **What is superseded is that sentence and nothing more**: the field
still holds "the additional authorities §6 admits a `Host` header to name", the
comparison is still literal, and the default is still empty for a gateway whose
remote listener is off. The alternative — leaving the empty list to start a
gateway no browser can reach — is the silent dead end §2 refuses one section
earlier, and it would be worse here, because the owner's evidence would be a
certificate warning on a phone.

### 7. The cookie half is marked `Secure` on that listener

> **Normative.** On the remote browser listener the cookie half ADR-0168 §6
> defines is additionally marked `Secure`. Every other attribute §6 requires —
> `HttpOnly`, `SameSite=Strict`, a path of `/`, no `Domain`, no persistent expiry —
> is unchanged, and the loopback listener is untouched.

**This is a stacked addition and not a change to ADR-0168 §6.** §6's clause lists
what the cookie is marked with; it is not an exclusive enumeration, and every
sentence of it stays true of a cookie that also carries `Secure`. Under ADR-0082
§1's test a reader holding only §6 is not made wrong, merely joined by an
obligation stated here — so the record is made in this ADR and nowhere else (§10).

**It is worth a clause rather than left to the lane because it changes a `may`
into a `must`.** Once the listener is HTTPS-only there is no plain-HTTP origin for
this gateway to leak the cookie half to (§2), so the attribute defends against a
narrow residual: a downgrade a future lane might introduce, or an attacker who can
make the browser attempt `http://` at the same authority. Cheap, and it removes
the one attribute of §6's set whose absence would look deliberate.

### 8. The two `Settings` fields, and why there is no third

| `Settings` field | Type | Default |
| --- | --- | --- |
| `gateway_remote_tls_certificate` | `str \| None` | unset |
| `gateway_remote_tls_key` | `str \| None` | unset |

> **Normative.** `gateway_remote_tls_certificate` and `gateway_remote_tls_key`
> hold filesystem paths to the certificate and to its private key. Both are unset
> by default.

> **Normative.** Three configurations are **refused at settings load**: either
> field set while `gateway_remote_address` is unset; either field unset while
> `gateway_remote_address` is set; and one set while the other is unset. Each is a
> configuration no reading makes true, and none is ignored silently — the rule
> ADR-0174 §8 applies to its two lists, for the reason it gives.

> **Normative.** The check splits across two places, as ADR-0174 §8's does.
> `Settings` refuses at load what it can decide without touching the filesystem or
> importing a subsystem: a value that is blank or has no UTF-8 form, and the three
> combinations above. The **gateway refuses at start**, before it binds or
> discloses a bootstrap value, what only the machine can answer: existence,
> custody and permissions (§3), that the key matches the certificate, that the
> moment of binding lies **inside the certificate's validity period at both
> bounds** — one not yet in force is refused exactly as an expired one is, and the
> refusal names the bound it failed — and §6's name check.

> **Normative.** No third field is added and none is owed. `gateway_remote_address`
> remains the switch (ADR-0174 §8); a field by which this listener could serve
> plain HTTP is what §2 refuses; and a renewal interval is not this system's to
> hold, because §4 makes renewal an owner act.

> **Normative.** The listener still binds `gateway_port`, and no port figure is
> added. ADR-0174 §8's clause that "no second port figure is added" is applied
> unchanged, and this ADR neither moves the listener to a privileged port nor
> obliges anyone to reach it at one.

**Why the paths are `Settings` fields rather than a fixed location.** The overlay
agent decides where it writes, and it differs by vendor, by platform and by how
the owner invoked it. A fixed path would be this system asserting a fact about a
program it does not own — and ADR-0174 §8 has the same shape one field over, where
`client_overlay_agent_socket` names a path rather than assuming one.

**Why `core` cannot make the whole check, in one sentence rather than by
inference.** The custody predicate lives in `wire/custody.py` and golden rule 2
forbids `core` importing a subsystem, so a `Settings` validator performing the walk
would be the boundary violation `lint-imports` fails on — the identical situation
ADR-0174 §8 resolved for `MAX_OVERLAY_IDENTITY_BYTES`, and resolved the same way:
one check, two places, each where the fact it needs already lives.

**Naming the fields here rather than leaving them to the lane** is what ADR-0174
§8 did for its three, on the ground ADR-0168 §8 took from ADR-0084 §3 and ADR-0083
§7, both of which take it from ADR-0074 §9.3: "a 'bounded default' with no figure
is two conforming stores handing the same continuation different history".
Transposed from a figure to a name, the same holds — two conforming deployments
configured by different words are two deployments one recipe cannot describe, and
`docs/guide/phone.md` is a recipe this decision has to rewrite.

### 9. What this decides no part of

> **Normative.** This ADR decides no `core/protocols.py` and no `core/types.py`
> surface. A lane implementing it that finds it needs either stops and owes its own
> contract ADR, merged first (golden rule 5, ADR-0015 §5).

> **Normative.** It changes no member of the connect exchange, no frame's encoding
> and no method's arguments or results, so no lane implementing it changes
> `PROTOCOL_VERSION` for it (ADR-0124 §9).

> **Normative.** A secure context is a **precondition and not an authorisation**.
> Nothing here decides that the browser surface captures a microphone, registers a
> service worker, subscribes to push, or reaches `crypto.subtle`. Each remains the
> decision of the ADR that decides that surface, and no lane may read this ADR as
> having granted, prepared or pre-authorised any of them.

**Deferred or refused by name, each with which of the two it is:**

- **The milestone-19 speech surface.** Untouched. The contract ADR for browser
  speech takes ADR-0174 §7's stop rather than working around it and makes a
  ratified scheme decision a precondition of its remote case (#1668); this ADR
  discharges that precondition and decides no part of that surface. It is cited by
  subject rather than by number because it is not on `main` as this is written.
- **What the assistant may say aloud, and how a withheld class is handled.**
  ADR-0199 decides it, and milestone 19's exit test has that as its second half
  — "a content class ruled unspeakable is deflected … not read aloud". This ADR
  unblocks the first half only, and reaches no clause of ADR-0199.
- **Milestone 20's push and service-worker use.** Merely becomes *reachable*.
  Nothing here schedules or authorises it, and ADR-0174 §10's direction rule — "the
  gateway never dials a browser" — is untouched and reinforced: a secure context is
  a browser classification, not a channel, and it gives the gateway no permission to
  open anything.
- **The loopback listener** (§2). Untouched, plain HTTP, potentially trustworthy
  for free.
- **The hub's own remote listener.** ADR-0124's third boundary carries no browser
  and needs no browser classification; nothing here reaches it, and no lane may
  read this ADR as adding TLS to it.
- **A gateway that obtains or renews its own certificate.** **Refused**, not
  deferred (§4). Reopening it means reopening ADR-0124 §3's transmission clause and
  the residency finding that rests on it.
- **A public door** — a name outside the overlay, a public CA for it, or a listener
  reachable from the internet. **Refused** here (§1); ADR-0174 §2's bind clause is
  unchanged. That it is refused *here* is not a ruling on whether it is ever taken.
- **Whether the client may accept a name for the hub's destination** (#912).
  Untouched (§6).
- **A durable session, a durable browser credential and a second live session.**
  Untouched; ADR-0168 §5 and ADR-0174 §9 govern, and this ADR neither reaches nor
  relaxes them.
- **Certificate revocation, rotation on compromise, and what an owner does about a
  leaked key.** Unreached. The key is the overlay's to reissue and the owner's to
  replace, and a gateway holding a replaced pair is corrected by the same act as a
  renewal: replace the files, restart. A lane wanting more than that owes its own
  decision.

### 10. Classification under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement to be made in this text, naming the clause and
applying ADR-0070 §1's test: would a reader holding only the earlier text now act
differently, or read one of its clauses more widely than it now holds?

**ADR-0004 §3's keyring clause — superseded, only as it reaches this class.** The
clause is "Tier 0 secrets are stored in the **OS keyring** via the `keyring`
library — never in the memory database, never in a committed file." A reader
holding only §3 puts the listener's private key in the keyring; after §3 above they
do not. The test comes out at a supersession, narrowly scoped: the class is closed
by §3's own words, and every other Tier 0 value stays under ADR-0004 §3 unchanged.
The key is not in a committed file and is not in the memory database, so those two
prohibitions are untouched and are not superseded.

**ADR-0004 §7's gating clause — superseded, only as it reaches the same class.**
The clause is "Access to Tier 0/1 data and every side-effecting tool call is gated
by the `permissions/` layer and recorded in an **audit trail**". A reader holding
only §7 expects the gateway's read of its key to be gated by `permissions/` and
recorded in the trail; it is neither. **Both halves are structurally unavailable
and neither is unavailable by choice**: `permissions/` runs inside the hub, the trail is
`<data_dir>/audit.db` which the hub owns exclusively (ADR-0083), and the read
happens at process start — before any hub connection, any session and any request
exists. There is no principal to check. The reader is the process the owner
started, on the machine whose key it is, opening a file the owner placed there; a
permission check would be the process asking itself.

> **Normative.** Three replacements stand in that exemption's place, and an
> implementation that omits any of them does not have it: the read is confined to
> **one purpose and one path** — building the listener's TLS context at bind, after
> which nothing else reads the key; **custody is the operating system's own
> control**, on a file owned by the gateway's user with the permissions and the
> ancestor walk §3 requires, so the access is gated by the OS where `permissions/`
> cannot reach it; and the **bind is disclosed** to the owner under §5, while a
> failure to read is a gateway that does not start and reports why (§2).

> **Normative.** The third replacement reaches a **bind and not a use**, and its
> **emission and not its retention**. It makes no read reviewable after the fact,
> it is a line on standard output rather than a trail, and where it lands is the
> operator's, exactly as ADR-0168 §6's emissions already are. No implementation and
> no later lane may present it as a durable or reviewable record, and none acquires
> a retention obligation from this ADR.

> **Normative.** ADR-0004 §7's second bullet — data minimisation — is not
> superseded and is not read either way, and neither is §7's gate over every other
> Tier 0 and Tier 1 access anywhere in this system.

**The record owed on ADR-0004, written here in full for the implementing lane to
copy.** ADR-0004's `Status` line carries the pre-ADR-0070 `Accepted, partially
superseded …` shape, and **it keeps it**: ADR-0070 §4 names ADR-0004 in the list of
lines it grandfathers, and rules that "reformatting a ratified status line to the
new leading-token form is a forward-only convention, not a licence to rewrite
settled records … New partial supersessions use the leading-token form; the
existing ones stand." What §4's accumulation rule asks of a seventh pair is that it
be added without dropping the six, which is what five earlier ADRs have each done
to this same line. The whole line, with the new pair and no other change, and the
same pair stated in the dated note ADR-0070 §1 requires:

```text
- Status: Accepted, partially superseded by ADR-0017 (§2's egress clause), ADR-0124 (§6's delete clause and §7's gating clause, each only as it reaches a device the owner has enrolled), ADR-0125 (§3's reader clause), ADR-0126 (§6's Tier 0 purge clause as it reaches a credential held outside the keyring, and §7's gating clause, each only for the offline whole-installation delete), ADR-0155 (§2's residency clause), ADR-0172 (§3's keyring clause, §6's Tier 0 purge clause and §7's gating clause, each only as it reaches a web-session credential) and ADR-0202 (§3's keyring clause and §7's gating clause, each only as it reaches the remote browser listener's TLS key material)
```

**ADR-0174 §7's first clause — superseded.** The clause is "The remote browser
listener speaks the same plain HTTP the loopback listener speaks. This ADR decides
no transport-layer security arrangement for it, authorises no certificate, no key
material and no certificate-provisioning act, and **no lane may read §2's
end-to-end encryption as supplying a secure context in a browser**." A reader
holding only it serves plain HTTP and authorises no certificate; after §§1–3 above
they do neither. The supersession is scoped to the plain-HTTP and
no-TLS-arrangement half. **Its last limb is kept and is not superseded**: nothing
here reads §2's encryption as supplying a secure context — the classification comes
from a certificate, which is a different property, and that is the distinction §7
drew and this ADR relies on.

**ADR-0174 §7's second clause — satisfied, not superseded, and no record owed.**
It requires a lane finding a secure-context capability to stop and to owe "a
ratified decision on the scheme". Every sentence stays true: a lane still stops,
and what it owes now exists. A reader holding only that clause acts identically —
they look for the ratified decision — so under ADR-0082 §1 there is nothing to
record. It is not read as authorising any capability either; §9 keeps that where §7
put it.

**ADR-0174 §11's deferral bullet — covered by the §7 record, and no separate pair
is owed.** The bullet — "A transport-layer security arrangement for the remote
browser listener (§7). Fires when …" — is unmarked prose in a marked ADR, so under
ADR-0089 §3 it supplies no obligation of its own; its subject is §7's clause, and
the §7 pair is what a reader arriving at §11 needs. Recording it as a second pair
would be the book-keeping ADR-0082 §1 refuses. The dated note ADR-0070 §1 requires
on ADR-0174 says both, which is where a reader is told the deferral landed.

**ADR-0174 §8's empty default for `gateway_remote_host_names` — superseded, only
for a configured remote listener.** The sentence is "Empty is the default, so a
gateway configured on serves the address it bound and nothing else." §6 above has
such a gateway refuse to start until a configured name matches the certificate, so
a reader holding only §8 acts differently. §6 argues it and bounds it; nothing else
in §8's clause for that field moves, and the two other fields' clauses are
untouched.

**ADR-0174 §6's delegation clause — superseded, as to its *when it is refused*
limb and nothing else.** The clause is "`gateway_remote_host_names` is §8's field
and §8 is the single statement of what it holds, what its default is and when it
is refused." §6 above states a refusal condition for that field — every configured
element covered by the certificate — and states it here rather than in §8, so a
reader holding only ADR-0174 §6 reads that delegation more widely than it now
holds and takes §8's conditions for the complete set. That is ADR-0070 §1's second
limb. **The scope is that limb**: what the field holds is unchanged; its default is
still §8's to state, moved only by the sentence of §8 recorded above; and §6's own
second sentence — "This section states only what the gateway does with it, and adds
no condition on it" — stays true, because ADR-0174 §6 itself gains nothing. §6 of
this ADR carries the argument, and records that an earlier draft classified this as
a stacked addition on the ground that §8's sentences stay true, which is so and
answers the wrong clause.

**The record owed on ADR-0174, written here for the implementing lane to copy.**
Its `Status` line reads `Accepted` today, so under ADR-0070 §4 the supersession
leads and `Accepted` is dropped; ADR-0082 §2 then puts the amendment record in the
appended dated note rather than as a `Status` qualifier, and ADR-0070 §1 requires
that note in every case. The line becomes:

```text
- Status: Partially superseded by ADR-0202 (§7's plain-HTTP clause with the transport-layer security arrangement §11 deferred alongside it, §8's empty default for the remote host-name list as it reaches a configured remote browser listener, and §6's delegation to §8 of when that list is refused, as it reaches certificate coverage)
```

**A stacked addition, recorded here and nowhere else** (ADR-0082 §1): the public
disclosure §4 accepts. ADR-0124 §3's marked clause enumerates what an overlay's
operator comes to hold and accepts that consequence; it does not say that nothing
else is ever disclosed, so no sentence of it becomes false or over-wide. §4 makes
its own acceptance, of its own disclosure, caused by an owner act this ADR
requires. §3's revisit condition is honoured by making that acceptance here rather
than reading it into §3's.

**A second stacked addition, likewise recorded only here**: §7's `Secure` attribute
on ADR-0168 §6's cookie half. §6's clause lists what the cookie carries and stays
true of one carrying more.

**A third, likewise**: §5's ordering of ADR-0174 §3's identity check ahead of the
TLS handshake. Every clause of §3 stays true — the identity is still obtained
before anything is served, still before ADR-0168 §7's checks and before any session
is read, and still from the agent on the gateway's own machine. What is added is an
ordering against an event §3 had no occasion to mention.

**Examined and found to owe no record**, clause by clause:

- **ADR-0124 §2** — the transport posture is unchanged; the listener still binds
  only an overlay address, and TLS is stacked on top of the overlay's encryption
  rather than replacing it. §2's three properties are still required and still
  supplied.
- **ADR-0124 §3** — both marked clauses stay true (above). No component of this
  system transmits to a control plane, so the residency finding stands on the
  condition it names.
- **ADR-0125 §2, §5 and §8** — no scope is added, no face is acquired by
  `interfaces`, and §8's file-read prohibition carries its own scope, which this
  key falls outside (§3).
- **ADR-0168 §2, §5, §6, §7 and §9** — the loopback listener is untouched; the
  bootstrap value's minting and single disclosure are untouched; §6's record
  enumeration gains no member (§5) and its cookie clause stays true (§7); the
  hub-down legibility clauses are untouched.
- **ADR-0172** — no clause is cited, widened or relied on (§3). Its class stays the
  three values it enumerates, and this ADR's class is disjoint from it.
- **ADR-0174 §2's loopback-availability clause** — examined on architecture
  review's first-round reading of it, and no record owed. The clause is "that
  loopback listener is bound whether or not this one is", and its subject is
  whether the remote listener is *configured on*. §2 of this ADR adds a start-time
  refusal, so a gateway with a broken certificate binds nothing — but ADR-0174
  already has two such conditions of its own, §2's load refusal of a bad
  `gateway_remote_address` and §8's start refusal of an over-long overlay identity,
  and both end in a process that does not run. A reader holding only §2 who
  configures the remote listener badly is already told the configuration is refused
  rather than bound; they act identically. Writing the record the reading asks for
  would declare an amendment no clause of §2 fails the test for, which ADR-0082 §1
  rules is wrong "however the declaration reads".
- **ADR-0174 §2's other clauses, §3, §4, §5, §9 and §10** — each stays true. §2's
  bind and off-unless-configured clauses are applied unchanged and its proxy
  prohibition is reinforced (§1); §3's identity check is ordered, not modified (§5);
  §4's admission is untouched; §5's carry-over is untouched; §9's one-mint rule is
  untouched; §10's direction rule is reinforced (§9). **ADR-0174 §6 is deliberately
  not in this list**: its `Host`-admission and resolves-nothing clauses gain no rule
  and are untouched (§6), but its delegation clause is superseded on the record
  above.
- **ADR-0174 §8, apart from the one sentence recorded above** — its three fields are
  joined by two, and a settings table that "carries no clause saying it is complete"
  is not an exclusive enumeration, which is the ground ADR-0182 §9 established for
  ADR-0168 §8's table where it found no record owed for the fields ADR-0174 §8 and
  ADR-0175 §8 had themselves added. §8's refusals, its shared-port clause and its
  device-list clauses are applied unchanged.
- **ADR-0004 §1, §2, §4 and §5** — the tiers are applied, not changed; residency is
  untouched (§4); §4's encryption-at-rest decision is untouched, and its `0600`
  posture is applied rather than modified; §5's rule that logs carry Tier 2 only is
  applied by §5's Tier 2 classification.

## Consequences

**One implementation lane, and its first act is the two records.** The lane is
`interfaces/gateway/` — binding the listener with a TLS context, the start-up
refusals of §§2, 3, 6 and 8, and §5's disclosure — plus the `Settings` fields and
their load-time refusals, plus the `app/` wiring that hands the gateway what it
needs. Before any of that it writes the two records §10 spells out, on ADR-0004's
`Status` line and dated note and on ADR-0174's, copying the scope text verbatim.
Nothing implements against this ADR until it merges (ADR-0015 §5, golden rule 5).

**The owner gains one operating act per gateway host, and one recurring one.**
`docs/guide/phone.md` is where both belong: its step 3 gains the two settings, its
step 4's "read what it prints" gains the certificate's name and expiry, and its
step 5 — today "type the `http://`", with a paragraph explaining that `https://`
"does not work here and is not meant to" — inverts. The same page's warning that
microphone capture is unavailable over this listener comes out. That rewrite is the
implementing lane's, and it is the user-visible half of this decision.

**An owner upgrading an existing deployment starts a new session, and nothing has
to be written to make that happen.** An origin is scheme, host and port, so
`https://name:8422` is not the origin `http://100.86.154.22:8422` was: the cookie
half is not presented there, ADR-0168 §6 scopes the header half to "scheme, host
and port" so browser storage does not carry over, and ADR-0174 §6's `Origin` check
compares against the authority the new `Host` names. The phone exchanges a fresh
bootstrap value, once, and that is the whole migration. It is worth stating because
the alternative reading — that an upgraded gateway silently keeps admitting an old
session across a scheme change — is the one nobody wants to discover by testing.

**Milestone 19's exit test stands as written**, and #1668 closes when this ADR is
ratified. The remote half of the browser speech surface stops being blocked; what
it is then permitted to do is that surface's own ADR's business (§9).

**What gets harder.** A gateway with a remote listener now has one more way to fail
to start, and an expired certificate takes the whole gateway down rather than
degrading it — deliberately (§2), and stated as a residual there. An owner who
never renews discovers it at a restart rather than at the moment of expiry. And the
machine's overlay name becomes public where it was the overlay operator's alone,
with that operator learning the issuance besides (§4).

**What gets easier.** Every secure-context capability the browser surface may later
want — push, service workers, `crypto.subtle` — becomes reachable on the remote
listener without a second scheme decision, which is why §9 is explicit that
reachable is not authorised. The mistyped-address residual ADR-0174 §3 stated
narrows (§6). And an owner who could previously reach the gateway at either of two
authorities is pushed toward the one the certificate names, which is the choice
ADR-0174 §6 already told them to make.

## Alternatives considered

- **A self-signed certificate.** Cheapest by a distance: no control plane, no
  public log, no name dependency, no renewal story worth the name. *Rejected* in §1
  on ADR-0174 §7's ground — it "trains the owner to click through a warning, which
  is a habit worth more than the capability" — and on the sharper form of that
  argument in Context: the browser's trust decision is the mechanism being bought,
  so teaching the owner to overrule it spends what it buys. A trusted local root
  installed on the phone is the same objection one step further along, and it adds
  an operating act on every browsing device rather than one on the gateway host.
- **A root the owner administers, admitted beside the public one.** Drafted after
  round 5's finding and withdrawn at round 9, and §1 records why: it is a genuinely
  better privacy outcome for whoever has it — a secure context with nothing
  published — but it splits the issuance requirement from the trust requirement,
  splits §4's disclosure account in two, and drew a fresh contradiction in each of
  the two rounds it survived. *Rejected* in §1: its beneficiary is an owner whose
  device already trusts an authority they run and who did not install it for this,
  and installing one for this is what §1 refuses. An owner who really is in that
  position has a superseding ADR available, on evidence this one lacks.
- **An overlay's own private certificate authority.** The shape architecture review
  found in an earlier draft's vendor-neutral clause, and the reason §1 now carries a
  trust requirement: an overlay may well issue for a name it assigns, and if the
  browsing device does not already trust the chain the owner gets the same warning
  and the same withheld microphone. *Rejected* in §1 — it is the self-signed route
  arrived at by a longer path, and it would have made this ADR buy nothing at all.
- **Terminating TLS in the overlay's own "serve" feature.** It would need no
  certificate handling in this repository at all. *Rejected* in §1, on ADR-0174 §2's
  mechanical ground rather than a policy one: a terminating proxy destroys the peer
  identity ADR-0174 §3 requires, so the arrangement that looks like a shortcut is
  the one that cannot satisfy the boundary.
- **A certificate for a name the owner controls, from a public CA.** It removes the
  dependence on the overlay's issuance entirely and works with any overlay.
  *Rejected* in §1: it is the first half of a public door, and the only thing then
  keeping the listener off the internet is a bind clause. It is refused rather than
  deferred, and refusing it is not a ruling on whether a public door is ever built.
- **HTTPS as an option beside plain HTTP.** The compatible move, and it would keep
  today's `docs/guide/phone.md` recipe working unchanged. *Rejected* in §2: an
  optional secure context is exactly the surface that produces "it works except the
  mic", a failure a browser gives no legible account of. Making the scheme a
  property of the listener puts the failure at start-up where the gateway can
  explain it.
- **Bind the loopback listener and continue when the certificate is missing or
  expired.** Gentler, and it keeps the local browser working. *Rejected* in §2: it
  is silent degradation moved to a different place, and it leaves the owner's phone
  with a page that will not load and nothing anywhere saying why. Unsetting
  `gateway_remote_address` is the same outcome as an explicit act.
- **Hold the key in the OS keyring behind ADR-0125's seam.** The corpus's default
  home for a Tier 0 value, and it would owe no supersession of ADR-0004 §3.
  *Rejected* in §3: `SecretScope` is closed at three members and a fourth is
  `core/types.py` surface (ADR-0125 §2), `interfaces` holds neither face (§8), and
  the route would have this system keep a second durable copy of a key the overlay
  agent owns and rewrites on every renewal — worse than the file the agent already
  keeps, at the price of two contract decisions.
- **Have the gateway obtain and renew the certificate itself.** It would remove the
  owner's recurring act, which is the one real cost of this decision. *Rejected* in
  §4: it makes a component of this system transmit to an overlay control plane,
  which ADR-0124 §3 forbids in terms and which its residency finding explicitly
  rests on. The convenience is not for sale at that price.
- **Have the gateway watch the files and reload on renewal.** It would remove the
  restart. *Rejected* in §4 as machinery buying little: a gateway process already
  bounds a session's life and mints one bootstrap value per process (ADR-0168 §4,
  §5), so a restart is an act the owner already knows, and §5's expiry disclosure
  makes it a scheduled one rather than a surprise.
- **Rule milestone 19's exit met on a loopback browser and carry the remote case
  forward.** #1668's option 2, and it needs no decision at all. *Rejected by the
  owner's ruling of 2026-08-27*, recorded on #1668: option 1, ratify the scheme,
  exit test as written. It is recorded here because the ruling is what makes this
  ADR's existence a decision rather than an assumption.
