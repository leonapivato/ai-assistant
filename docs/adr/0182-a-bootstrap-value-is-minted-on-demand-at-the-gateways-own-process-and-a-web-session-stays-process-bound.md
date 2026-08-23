# 182. A bootstrap value is minted on demand at the gateway's own process, and a web session stays process-bound

- Status: Proposed
- Date: 2026-08-23

- **This is `track:web-client` milestone 16's sessions decision** (#1230, #1429).
  Milestone 16 is *polish and first-run: reconnect, error states, session
  persistence, mobile layout, install and first-run docs*, and its exit test is
  that a stranger brings hub, gateway and browser up on a fresh machine from the
  docs alone. This ADR decides the two of those the corpus has held open by
  name — **session persistence** and the reconnect rule the page may act
  under — and nothing else.
- **It is the revisit ADR-0168 §12 named and ADR-0174 §9 declined to be.** Both
  defer a second live session, a durable session and several browsers admitted at
  once to milestone 16 by name, with session persistence as the trigger; ADR-0175
  §10 repeats the deferral. This is that decision, and it closes #1320 and #1329,
  which ADR-0174 §9 ruled hold until it.
- **No implementation lands with it.** No `src/`, no `tests/`. Lane 2 of #1429
  implements it after it merges.
- **It decides no `core/protocols.py` and no `core/types.py` surface**, so golden
  rule 5 is not triggered. It adds one `Settings` field (§3), which is contract
  surface in ADR-0054's sense and not `core` Protocol or type surface, so no triad
  is owed.
- **It partially supersedes two ADRs, each narrowly.** ADR-0168 §5's two
  one-mint-per-process clauses (§1, §2), and ADR-0172 §1's third class member as
  it reaches a gateway's second and later bootstrap value (§5). One record lands
  on each in this same change; §9 applies ADR-0070 §1's test clause by clause to
  every other ADR a reader might expect this to reach, and finds two dated notes
  owed and no further supersession.
- **The persistence question is ruled the way ADR-0172 §2 wanted it ruled**: a
  session still ends with the gateway process, so ADR-0004 §3, §6 and §7's three
  exemptions keep the condition ADR-0172 §2's replacement (d) makes of that bound.
  "Persistence" is satisfied by survival across a reload, which already holds, plus
  re-entry that costs a keystroke rather than a restart.

## Context

### What the milestone asks for, and what the tree actually does

`docs/roadmap.md`'s milestone-16 line asks for "session persistence" among four
other things, and the word has to be read against what the shipped gateway does
rather than against what it sounds like. Two facts, checked at `origin/main`
rather than remembered.

**A reload already keeps the session.** ADR-0168 §6 puts the header half "in
browser storage scoped to **scheme, host and port** and shared across that
origin's tabs", and the cookie half is a cookie. Neither is lost when the page
reloads, and `sessions.py` reconstructs nothing — it verifies two values a browser
still holds against a table it still has. So the reload case, which is what most
readers mean by persistence, is not open.

**A second browser is not reachable at all.** ADR-0168 §5 mints "one bootstrap
value at start", discloses it once on standard output, and "after it the gateway
mints no further session until its process is restarted". `run_gateway` implements
exactly that: mint, disclose through the injected `disclose` callback, then serve.
An owner with a laptop browser and a phone browser has to stop the gateway and
start it again, which ends the laptop's session to admit the phone's. ADR-0168's
own Consequences state the cost — "every gateway restart logs every browser out,
and a second browser needs a restart" — and ADR-0174 §9 restates it one milestone
later in the place it becomes annoying rather than theoretical, because milestone
14 put the second browser on a phone.

So the milestone's word covers two different things, only one of which is open,
and the open one is **re-entry** rather than durability.

### The two issues that have been waiting for this decision

**#1320.** ADR-0168 §4 has the gateway "admit at most `gateway_max_sessions` live
sessions" and refuse beyond it rather than evict, and §8 gives the field a default
of 8. Under §5 at most one session is ever live in a process, so no execution
reaches a second and every strictly positive value of the field behaves
identically. The issue's own reading is the one taken here: "on that reading the
field is early rather than wrong, and the honest fix is a sentence in the
superseding ADR saying so."

**#1329.** §8's figures are session bounds — `gateway_session_ttl` and
`gateway_session_idle_timeout`, both spent by §4 — and an **unexchanged bootstrap
value is not a session**. No clause gives one a clock, so two conforming gateways
differ: one accepts the value until the process exits, another does not. §8 opens
by refusing exactly that shape, quoting ADR-0083 §7 and ADR-0093 §5 — "a 'bounded
default' with no figure is two conforming stores handing the same continuation
different history". ADR-0174 §9 examined the issue, changed the physical story
(the value is now carried to another device by hand, so the interval between
disclosure and exchange is plausibly minutes) and deliberately supplied no figure,
leaving it here.

Both are artefacts of one rule, which is why #1329 says "whoever revisits §5 …
should hold them together". This ADR does.

### The condition three privacy exemptions hang on

ADR-0172 is the narrow supersession ADR-0168 §6 made a prerequisite: it takes
ADR-0004 §3's keyring clause, §6's Tier 0 purge clause and §7's gating clause for
the web-session credential class and nothing else. Its replacement (d) is the one
doing the work — "**Bounded power rather than durable custody.** Every value in
the class is minted by this system rather than held on behalf of a third party,
admits only what the owner sitting at that machine can already do, and **ceases to
admit anything** no later than the end of the gateway process" — and §6 makes the
whole set of replacements a **condition** rather than a description, so "an
implementation that starts persisting a session table loses the exemption at the
moment it does so, and is then in breach of ADR-0004 §3 as written".

ADR-0172 §2 then says in terms that the exemption "does not authorise a **durable**
browser-held credential — one that still admits after a gateway restart", and that
a design removing the bound "owes its own ratified decision". ADR-0172 §5 scopes
its no-record-on-a-successful-read ruling the same way: "A design in which a
session still admits after a restart reopens it and may not inherit it."

That is the price list for durability, and it is the reason this decision separates
the two halves of "persistence" rather than granting both. Re-entry costs one
supersession of a rule about *how many* values a process mints. Durability costs a
second Tier 0 secret, the reopening of three ADR-0004 exemptions, and ADR-0168
§13's `VISION.md` argument made again on harder ground. The milestone's exit test —
a stranger standing the system up from the docs — needs the first and asks nothing
of the second.

### What the page does today when a connection dies

Nothing. The survey behind #1429 found no `visibilitychange` handler, no `online`
handler and no retry anywhere in `interfaces/gateway/assets/`: a phone that
backgrounds its browser shows a stale "Watching" until the owner clicks something.
ADR-0175 §4 already rules the gateway side — a poll it cannot complete "ends every
open delivery stream with a terminal value reporting it", and the gateway "polls
again only when a browser establishes a delivery stream afresh, and retries no poll
of its own motion" — and the same section states the cost of the stream it
abandons: "costs the abandoned browser a reconnect — which is free, because a
session outlives its connections". Free for whom is the question this decision has
to answer, because ADR-0168 §9 forbids the gateway retrying **silently**, and a
page that reconnects behind the owner's back is that prohibition defeated one layer
out — the same shape ADR-0168 §3 describes for admission.

## Decision

We will supersede ADR-0168 §5's one-mint-per-process rule with a mint the owner
performs at the gateway's own process, bound an unexchanged value with a named
figure, make `gateway_max_sessions` binding at the act that raises the count, keep a session's power
ended by the gateway process so ADR-0004's three exemptions keep their condition,
and state the one rule under which the page may re-arm a connection of its own
motion.

### 1. The mint act is performed at the gateway's own process, and it is not a request

> **Normative.** A gateway process mints a bootstrap value at start, exactly as
> ADR-0168 §5 requires, and mints a further one whenever the owner performs the
> **mint act** at the machine that runs it. Each value is minted from at least 128
> bits of the operating system's cryptographic random source, is exchangeable for
> exactly one session, and is consumed by that exchange, exactly as ADR-0168 §5
> requires of the first.

> **Normative.** The mint act is the delivery of `SIGUSR1` to the gateway process,
> and it is the whole of the act. The gateway installs that disposition for the
> life of its listener, and a gateway that cannot install it starts anyway and
> reports at start that the act is unavailable, rather than refusing to serve.

> **Normative.** A minted value is disclosed exactly as ADR-0168 §5 requires of the
> first — once, on the gateway's own standard output, and nowhere else: not in a
> log record, not in an error, not in a response body, and not in any URL a browser
> transmits to a server.

> **Normative.** The mint act is **ordered**, and the order is part of the rule: the
> gateway mints a candidate, discloses it, and only on a **successful** disclosure
> does that candidate become the outstanding value of §2 and the previously
> outstanding value cease. Nothing about a previously outstanding value changes
> before that point.

> **Normative.** A value the gateway cannot disclose is **not minted**: the gateway
> destroys the candidate, reports the failure, leaves any previously outstanding
> value exactly as it was — still outstanding, still on its own clock — and keeps
> every live session and keeps serving.
> ADR-0168 §5's "a gateway that cannot disclose its bootstrap value does not start"
> binds the value minted at start and is untouched; it does not reach a later mint,
> and no lane may read it as obliging a gateway to stop.

> **Normative.** Every disclosure names the mint act and the gateway's own process
> id, so that the act is discoverable from the disclosure rather than from a
> document.

> **Normative.** The clause above is robustness and **not a platform claim**.
> This system's resident processes already require a platform with `AF_UNIX`
> sockets and asyncio signal dispositions — `service/transport.py` binds the hub's
> listener with `asyncio.start_unix_server` and `service/hub.py` installs its stop
> dispositions with `loop.add_signal_handler` — so a platform on which `SIGUSR1`
> cannot be installed runs no hub of this system, and a gateway there reaches no
> assistant however many browsers it admits. No lane may cite that clause toward a
> second mint act, toward a request-borne mint, or toward any claim that a gateway
> whose hub is merely **unreachable** admits nobody: ADR-0168 §9 requires the
> opposite, and §9 of this ADR leaves it untouched.

> **Normative.** **No request on any listener mints a bootstrap value.** ADR-0168
> §3's two pre-session exceptions keep their extent and gain no third; ADR-0168
> §6's four request classes gain no fifth; and no lane may add a path, a request
> shape, a header, a query parameter or a pre-session exception by which a request
> causes a mint, on the loopback listener or on ADR-0174 §2's remote browser
> listener.

**The act needs standing that reaching the port does not confer, and that is the
whole argument.** ADR-0168 §3 is explicit that the gateway's port "carries no
`0600` bit and no overlay identity", so "every local process and every local user"
can reach it; that is why a session exists at all. An act that mints a bootstrap
value is an act that produces the thing which admits a browser to the device's
whole authority, so putting it behind the port would hand every local process the
ability to cause one — and if the value came back in the response, the ability to
*hold* one. Signal delivery is the operating system's own access control on this
question: `kill(2)` succeeds for the owner's own uid and for root, which is the
same standing ADR-0168 §5's exposure argument already assumes ("a place they
already have the standing to read the process's own memory from"). A process with
that standing can read the gateway's memory outright and needs no mint act; a
process without it cannot perform one.

**It is also stronger than "loopback-only", not merely different.** ADR-0174 §3
splits the two listeners and requires the gateway to obtain a browsing device's
overlay identity "from nothing the peer asserts", and a mint path would have needed
its own clause saying it is served on neither. A signal has no network path at all,
so the remote listener cannot reach it by construction rather than by a clause
someone could get wrong, and the split ADR-0174 §3 draws needs no new member.

**The signal is named rather than left to the implementation, for §8's reason one
level down.** ADR-0168 §8 names its figures because "a 'bounded default' with no
figure is two conforming stores handing the same continuation different history",
and an unnamed signal is the same defect: two conforming gateways would answer
different signals and the first-run guide could not tell a stranger what to send.
`SIGUSR1` is the disposition reserved for exactly this, and `SIGHUP` is not
available — `service/hub.py` already installs it as the ignored signal on ADR-0083
§13's "a restart is the reload", and a terminal hangup delivers it, which would
mint a live admission ticket every time an owner closed a window.

**Naming the act in the disclosure is what makes it findable, and it is cheap.**
ADR-0083 §4's principle is that "a signal that silently does nothing is worse than
one that is documented as doing nothing"; the converse holds for one that does
something nobody knows about. The gateway already writes an origin and a value to
its own standard output; adding the act and its own process id costs one line and
means the most recent disclosure always carries the recipe. Its process id is a
Tier 2 fact about itself, and nothing in ADR-0168 §6's record enumeration is
engaged, because a disclosure is not a record.

**The degradation clause is not the seam by which a second act arrives, and it is
worth being blunt about that.** Adversarial review read it as leaving milestone 16's
re-entry unreachable on a platform without `SIGUSR1`, on the ground that
`pyproject.toml` names the Windows Credential Vault among the backends `keyring`
supplies. That comment is about a dependency's reach and not about this system's:
the hub's own listener is an `AF_UNIX` socket whose peer credentials ADR-0084 §1
reads from the kernel, and the hub installs signal dispositions unconditionally, so
the arrangement in question is one **no hub of this system can be started in** — not
one whose hub is temporarily down. The difference matters and an earlier draft of
this paragraph elided it: ADR-0168 §9 requires the gateway to start and serve
"whether or not the hub is reachable", the bootstrap exchange reaches the session
table and not the hub, and a browser admitted while the hub is down is admitted
exactly as one admitted while it is up — it simply gets §9's legible transport
failure when it asks for something. Adversarial review found the over-claim on the
second round. What survives it is the narrower fact that carried the argument: §5's
re-entry claim and the Consequences' keystroke are claims about the platform this
system runs on rather than about every platform Python does. Where that ever stops being true, the
answer is a decision about this system's platform and not a second mint act bolted
onto this one.

**A failed later mint does not stop the gateway, and the asymmetry with §5 is
deliberate.** §5's refusal to start protects an owner from a gateway answering a
port with a value nobody can present. A later mint is different in the one way that
matters: sessions are already live, and stopping would end all of them to punish a
convenience act that failed. Reporting the failure and continuing leaves the owner
exactly where they were, which is the direction ADR-0083's ruling 4 points.

**"Exactly where they were" is only true if the order is fixed, and an earlier draft
left it open.** That draft had §2 replace the outstanding value on a mint and §1
destroy a value it could not disclose, without saying which happened first — so an
implementation that replaced before disclosing left the owner with **no** usable
value after a failure they did not cause, and one that replaced after disclosing left
the old value live. Two conforming gateways, different admission results for the same
value, which is the defect §3's opening quotes ADR-0083 §7 about. Adversarial review
found it on the third round. Disclosure first is the branch that keeps the claim
above true, and it is also the safer half of the two: the failure mode it accepts is
an old value living out its own clock, which §3 already bounds, rather than an owner
locked out of a running gateway by a supervisor closing a pipe.

### 2. One outstanding value at a time, and four ways it ceases

> **Normative.** At most **one** unexchanged bootstrap value **admits** at a time.
> A **disclosed** mint (§1) replaces the outstanding value, which ceases to admit
> anything at that moment, so there is no instant at which two values admit — not
> even the width of a mint act, because §1 orders disclosure before replacement.

> **Normative.** The invariant above is about what **admits**, not about what the
> gateway holds. An undisclosed **candidate** is not a value (§3), it admits
> nothing, and **no exchange accepts one before the disclosure that promotes it**.
> Its coexistence in the gateway's memory with the still-outstanding value, for the
> width of a disclosure, is required by §1's order and is not two values standing.

> **Normative.** An outstanding value ceases to admit anything on the first of
> four events, and there is no fifth: its exchange (ADR-0168 §5's single use),
> `gateway_bootstrap_ttl`'s expiry (§3), its replacement by a fresh mint, and the
> end of the gateway process (ADR-0168 §4).

> **Normative.** The gateway destroys a value that has ceased **continuously**,
> rather than at a checkpoint or on the next exchange that happens to arrive — the
> discipline ADR-0168 §4 requires of an expired session, applied to this value for
> the same reason.

> **Normative.** ADR-0168 §5's disclosure rule on a failed exchange is untouched
> and binds every refusal this ADR creates: a failed exchange discloses only that
> it failed, "never whether the value was well-formed, whether one is still
> outstanding, or whether a session already exists" — and never which of the four
> events above ended the value it carried.

**The invariant is stated over admission because §1's order makes the custody
reading impossible to satisfy.** An earlier draft said "no gateway holds two — not
even for the width of a mint act, **because** §1 orders disclosure before
replacement", which offers §1 as the ground for the one thing §1 forbids: minting a
candidate and disclosing it before promotion means the candidate and the outstanding
value are both in memory for the width of the write. Adversarial review found it on
the eighth round. Read literally, an implementer resolving the contradiction in §2's
favour would destroy the old value before disclosing — the exact defect §1's ordering
was fixed on the third round to remove. The rest of this ADR already reads the way
the clause above now does: §3 says a candidate "is not yet a value", and §4's own
argument turns on "an old value exchanged while a candidate is being disclosed". What
the invariant has to carry is that no two values ever admit, which is the hazard the
next paragraph is about, and the clause naming the exchange is what makes that true
of the interval rather than merely asserted about it.

**One outstanding value is what keeps this from needing a ceiling of its own.**
Several values standing at once would be a pool: bounded by nothing but the owner's
patience, growing every time a mint is performed and not spent, each member a live
admission ticket sitting in the terminal's scrollback. Bounding it would have cost
a further figure and a further refusal, and ADR-0094 §9's permission is for edge
state "bounded in size and in age". One value is bounded in size by the rule
itself, and §3 bounds it in age, so the pair satisfies §9 without a number.

**Replacement rather than refusal, because the owner's mental model is the screen
in front of them.** A gateway that refused to mint while a value stood would make
the act fail in the case an owner most often reaches it in — they minted, mistyped,
and want another. Replacing means the value on the screen is always the value that
works, which is the only invariant a first-run guide can state in one sentence. It
costs the owner the case where they mint twice deliberately and then try the first,
which fails legibly and is the same class of mistake as pasting a consumed value.

**The four events are enumerated rather than left to be inferred, because that is
what #1329 is about.** The issue's defect is not that a bootstrap value lives too
long; it is that a reader cannot tell a deliberate omission from an oversight. A
closed list of what ends a value, with a figure attached to the one event that had
none, is what removes the divergence between two conforming gateways.

### 3. The figure

Named here rather than left to the implementation, on ADR-0168 §8's ground, taken
from ADR-0084 §3 and ADR-0083 §7 and applied by ADR-0175 §8 to its own figure.

| `Settings` field | Type | Default |
| --- | --- | --- |
| `gateway_bootstrap_ttl` | `timedelta` | 10 min |

> **Normative.** It is refused at settings load unless it is strictly positive, in
> the `gt=timedelta(0)` form ADR-0083 §7 adopted and ADR-0168 §8 applied. It is not
> nullable and takes no value meaning "off", exactly as ADR-0168 §8's ten and
> ADR-0175 §8's one do.

> **Normative.** Its clock runs from the **successful disclosure** that promotes a
> candidate to the outstanding value (§1) — the same instant the previous outstanding
> value ceases — and from no other. A candidate not yet disclosed has no clock because
> it is not yet a value, and no implementation may key the clock on the first request
> that presents the value or on any later event.

> **Normative.** It is measured on a **monotonic** elapsed-time source — one the
> system clock being moved in either direction does not affect — and a value that
> has ceased is destroyed continuously, through the deferral seam ADR-0168 §4's own
> continuous destruction already uses.

> **Normative.** That source is **this figure's alone**. ADR-0168 §4's session
> bounds and ADR-0168 §8's two session figures are untouched, this ADR names no
> elapsed-time source for them, and no lane may read the clause above as having
> changed how a session's expiry is decided or as obliging one to align with the
> other.

> **Normative.** No load-time check relates it to `gateway_session_ttl`,
> `gateway_session_idle_timeout` or any other figure, and no lane adds one. It
> bounds a value that is not a session, so a relation to a session's bounds would
> be a claim about a fact neither figure is about.

**Ten minutes, and where the number comes from.** The act it has to survive is the
owner reading a value off one screen and entering it on another — walking to a
phone, unlocking it, opening the page, typing or pasting sixty-four characters.
Minutes, as ADR-0174 §9 already observed when it changed the physical story
("plausibly minutes rather than seconds"). Ten gives that a wide margin including a
retype, and it is short enough that a value in a terminal's scrollback is dead long
before the owner has scrolled past it. An owner who wants longer sets the field; the
default is chosen for the case the first-run guide describes.

**It is deliberately unrelated to the session figures, and stating that is the
point.** ADR-0168 §8 relates `gateway_session_idle_timeout` to `gateway_session_ttl`
because "an idle bound above the absolute lifetime is a limit that can never bind" —
a relation between two bounds on the same object. A bootstrap value is a different
object with a different life: a ten-minute ticket that opens a twelve-hour session is
coherent, and so is the reverse. ADR-0175 §8 refuses a cross-process check for the
same reason in a different direction, and the form is taken from there.

**Naming a monotonic source is ADR-0026's own revisit condition arriving, and it
is answered here for this figure rather than for the corpus.** ADR-0026 revisits
"when something needs a **monotonic** clock", and says in terms why its own seam is
not it: "`Clock` produces wall-clock instants; measuring an elapsed duration across
a DST transition or an NTP step is a different contract this one does not provide
and should not be stretched to." A ten-minute bound on a live admission ticket is
exactly such a duration — measured on the wall clock, an hour's step back keeps the
ticket admitting for seventy real minutes, and a step forward kills it on the spot —
so the clause above names the source instead of leaving it to be inferred, and binds
the destruction to the seam ADR-0168 §4 already spends. Adversarial review found it
on the first round.

**The two figures beside it are on a different clock, and this decision says so
rather than claiming they are not.** An earlier draft of the clause above added "so
a bootstrap value and a session do not age on two different clocks", which is false,
and both lenses found it on the second round. `SessionTable` **decides** expiry from
its injected wall-clock `now` — `_expired` compares that instant against
`expires_at` and against the idle bound, and `_rearm` computes its delay from it —
and uses `call_later` only to schedule the destruction. So a forward step of the
system clock can end a live session at once while an equally old bootstrap value
runs its full monotonic ten minutes. That divergence is real, it is a property of a
ratified decision this lane may not change, and the honest move is to bound the new
figure correctly, say in terms that the clause reaches nothing else, and file the
wider question. **What is deliberately not decided here** is whether ADR-0168 §8's
`gateway_session_ttl` and `gateway_session_idle_timeout` should carry the same
sentence. Requiring the source in text for one figure while two ratified figures on
the same object leave it unstated is a half-answer — but it is a better half than
putting the new figure on the clock that produced the hazard, and it is filed rather
than taken (#1439).

**The clock's origin is named because #1329 asked which one it is.** "Mint time?
Disclosure time?" — the disclosure, and §1's ordering is what decides it rather than
a preference. An earlier draft said "mint", on the reasoning that the two are
separated by the width of one act and nothing observable turns on the choice. That
was true before §1 fixed the order and false afterwards: the write is the act that can
block, so a gateway whose standard output is back-pressured could generate a
candidate, block for longer than the whole bound, and then promote a value already
past its clock — handing the owner a token that cannot admit a browser and giving them
no way to see why. Adversarial review found it on the fourth round. Keying the clock
on the promotion makes the value's life begin when the owner can first read it, which
is the only instant either of them can act from.

### 4. `gateway_max_sessions` binds, and the exchange is the one door it binds at

> **Normative.** ADR-0168 §4's ceiling clause — the gateway "admits at most
> `gateway_max_sessions` live sessions and **refuses** a mint beyond that ceiling
> rather than evicting an existing session to make room" — is untouched, is applied
> rather than narrowed, and is now reachable. Its default of 8 (ADR-0168 §8) is
> unchanged.

> **Normative.** The **bootstrap exchange is the only place the ceiling is
> enforced**, because it is the only act that raises the live session count. An
> exchange that would take the count past `gateway_max_sessions` is **refused**, and
> no session is minted. Nothing is evicted, no live session is shortened, and the
> value the exchange carried is consumed exactly as a spent value is, so a refused
> exchange is not a value the caller may present again.

> **Normative.** The mint act (§1) makes **no decision that depends on the live
> session count**. It is not refused at the ceiling, it mints and discloses exactly
> as §1 requires whatever the count is, and no lane may add a second ceiling check
> to it or to any other act.

> **Normative.** Every disclosure carries the live session count and
> `gateway_max_sessions` beside the value, as **information and not a refusal**, so
> that an owner minting into a full table learns it where they are standing. Being
> advisory is what makes it safe to state: it is a fact about the instant it was
> written and no act of the gateway turns on it.

> **Normative.** The browser learns only that the exchange failed. ADR-0168 §5's
> disclosure rule governs the response, so a ceiling refusal is indistinguishable
> to the browser from every other failed exchange.

> **Normative.** The refusal **is** recorded, and the record names the ceiling as
> the condition it was refused on, under ADR-0168 §6's record clause and inside its
> enumeration of permitted Tier 2 facts. That record is the owner's channel for the
> fact the browser is not told, and it reaches the same standard output the
> disclosure does.

**One enforcement point, at the act that changes the count, and the two drafts
before it are why the sentence is worth this much space.** The first draft refused
at *both* doors — the mint act and the exchange — on the reasoning that "sessions
expire, so the count at mint time is not the count at exchange time". That is true
and points the wrong way: expiry only lowers the count, and a ceiling is breached by
raising it. Architecture review found on the fourth round that the exchange branch
was therefore unreachable, which is precisely #1320's defect reintroduced by the
decision that closes it.

The second draft kept both and *stated* the unreachability. Adversarial review found
on the fifth round that the statement was false, by an interleaving the two earlier
rounds had created between them: §1 orders disclosure before promotion, so a mint act
at seven of eight live sessions can pass its ceiling check, begin disclosing, and —
if disclosure does not block request handling — have the still-outstanding old value
exchanged underneath it, reaching eight. The candidate then either promotes past a
ceiling that had refused it or is rejected after the owner has already read it. The
available repairs were both bad: making the whole act atomic against the exchange
means blocking the event loop on a write to a pipe that may be back-pressured, which
is the stall round four's finding was about; re-checking at promotion means refusing
a value already on the owner's screen, which is the same defect one step later.

**So the count stops being an input to the mint act at all.** The exchange owns the
invariant because the exchange owns the count, there is exactly one place to check
and one place to test, and no ordering between minting and exchanging can produce a
state the text does not describe — an old value exchanged while a candidate is being
disclosed is simply an old value spent, which it was entitled to be. What the owner
loses is a refusal at the terminal; what they get instead is the count printed beside
every value, which tells them the same thing without deciding anything, plus a value
that becomes spendable on its own if a session idles out inside its ten minutes. The
general lesson is the one ADR-0168 §8 records for its connection ceilings: bound the
thing the caller cannot fake, at the moment it changes, and do not spread one
invariant over two moments.

**The browser is told nothing and the owner is told everything, which is ADR-0168's
existing split rather than a new one.** §5 requires a failed exchange to disclose
only that it failed, and §6 requires the gateway to record a refusal with the
condition it was refused on. Those two clauses are already the shape of this answer:
a caller at the port learns nothing it could use to probe the gateway's state, and
the owner reading the gateway's own output learns which limit bound. Splitting them
differently — telling the browser the ceiling — would hand any local process a probe
for how many browsers the owner has admitted.

**A refused exchange consumes its value, and that is the conservative direction.**
The alternative leaves a live ticket outstanding after a failure the caller can
drive, which turns the ceiling into a way to keep a value alive. Consuming it costs
the owner one mint act in the case where they genuinely raced their own ceiling, and
that case ends with them closing a browser or raising the field.

**#1320 is answered in its own terms.** The field is early rather than wrong; the
sentence it asked the superseding ADR to carry is the first clause of this section;
and §4's prose defence of refusing rather than evicting — which turned on "any local
process that can mint sessions could log the owner out of their own browser,
silently" — is now true of a real population rather than of one that could not exist.
What can drive a mint is the owner's own standing (§1), and what can drive an
exchange is a value only the owner has seen, so the eviction weapon ADR-0131 §2
refuses is not handed out by making the ceiling reachable.

### 5. A session stays process-bound, and three exemptions keep their condition

> **Normative.** A web session's power still ends with the gateway process.
> ADR-0168 §4's clause — "Every session ends when the gateway process ends. A
> session does not survive a gateway restart, and the gateway reconstructs no
> session from anything a browser presents after a restart" — is untouched and is
> applied rather than narrowed.

> **Normative.** ADR-0172 §2's replacement (d) is satisfied unchanged, and this ADR
> makes it **more** true rather than less: every value in the web-session credential
> class still ceases to admit anything no later than the end of the gateway process,
> and a bootstrap value now additionally ceases on `gateway_bootstrap_ttl` and on
> replacement (§2) as well as on its single use. The ADR-0004 §3, §6 and §7
> exemptions ADR-0172 rules therefore keep their condition, and no lane may read
> this ADR as having removed it.

> **Normative.** ADR-0172 §1's class is widened in **cardinality and in nothing
> else**: its third member is each bootstrap value a gateway process mints and
> discloses, rather than the one such value ADR-0168 §5 permitted. No kind of value
> joins the class, the class stays closed, and ADR-0172 §1's prohibition on widening
> it by resemblance is applied rather than narrowed.

> **Normative.** ADR-0172 §5's ruling that no record is written for a Tier 0 read a
> live session admits is **not** reopened. That ruling is scoped to "a web session
> whose power ends with its gateway process", the bound is kept here, and this ADR
> adds no record on the admitted path and no obligation to write one.

> **Normative.** A **durable** session — one that still admits after a gateway
> restart — and a durable browser credential minted to that end are **refused** for
> this milestone. No lane may cite this ADR toward either, and a later decision that
> wants them owes its own ratified ADR, reopening ADR-0004 §3, §6 and §7 through
> ADR-0172 §2 and making ADR-0168 §13's `VISION.md` argument on durable edge state.

> **Normative.** Milestone 16's "session persistence" is satisfied by two things
> together and by nothing further: survival across a page reload, which ADR-0168 §6's
> origin-scoped storage already gives, and re-entry that costs the mint act of §1
> rather than a gateway restart.

**Cardinality is the only thing that moves, and saying so precisely is what keeps
ADR-0172's exemption intact.** That ADR defines its class "by what mints the value
rather than by what holds it", deliberately, so that it cannot grow "the moment any
later milestone puts a second value in a browser". A second bootstrap value is the
same kind of value minted by the same act of the same system for the same purpose,
and every one of §2's four replacements is satisfied by it as written: one purpose
and one path, nothing at rest on this system's side, custody by the browser
profile's own permissions, and bounded power. What a reader holding only ADR-0172 §1
would do is the reason a record is owed at all — its third member says "the bootstrap
value a gateway process mints and discloses **once**", and read literally that
sentence leaves a second value outside the class, which would put it outside the
ADR-0004 §3 exemption and therefore in breach of a clause it obeys in substance.
That is ADR-0070 §1's first limb on a scope word, and §9 records it.

**Durability is refused rather than deferred again, and the difference is worth the
sentence.** ADR-0168 §12 and ADR-0174 §9 and ADR-0175 §10 all defer it *to this
milestone*, so leaving it deferred a fourth time would be the corpus passing a
question round a circle. It is refused on its merits: nothing in milestone 16's exit
test asks for it, the re-entry act costs a keystroke, and buying it would reopen
three ADR-0004 exemptions and require a second Tier 0 secret — "a password whose
entropy a human chose, and the shape ADR-0124 §6 argued against on the credential it
*did* mint" (ADR-0168 §5). The trigger for revisiting is recorded in §8 rather than
left implicit.

**And the refusal is what makes the rest of this decision cheap.** Every clause
above is about how many short-lived values one process mints. None of them touches
where a value lives, how long it outlives a process, or what a delete act can reach —
which is why ADR-0172 §4's ruling that "the act that removes the class is stopping
the gateway process" is as true after this decision as before, and why §9 finds no
record owed on it.

### 6. The cookie half stays a session cookie, and the page says what that costs

> **Normative.** ADR-0168 §6's cookie clause is untouched: the cookie half stays
> marked `HttpOnly` and `SameSite=Strict`, with a path of `/`, no `Domain`
> attribute and **no persistent expiry**. No lane gives it one, and no lane reads
> this ADR as authorising one.

> **Normative.** ADR-0168 §6's separation of the cookie's attributes from the
> lifetime guarantee is applied rather than narrowed. A session's lifetime is
> decided by the gateway alone, and no clause of this ADR may be read as making a
> browser's own behaviour part of any guarantee — in either direction, so neither a
> browser that discards the cookie on close nor one that restores it is relied upon.

> **Normative.** The page states, in the page and without requiring an interaction
> to reveal it, three conditions of the session it is running under: that every
> session ends when the gateway process ends; that a session ends at
> `gateway_session_ttl` or after `gateway_session_idle_timeout` of no admitted
> request; and that closing the browser may end it, in which case re-entry is a fresh
> bootstrap value the owner mints at the gateway (§1).

> **Normative.** A browser presenting a header half the gateway does not admit is
> shown the bootstrap entry, presented as re-entry rather than as a fault. It is not
> rendered in the page's fault surface, and no clause of this ADR obliges the page to
> distinguish which of §2's or ADR-0168 §4's conditions ended the session — the
> gateway does not tell it, and ADR-0168 §5's disclosure rule is why.

> **Normative.** The page **may** discard a header half the gateway refused. No
> clause obliges it to: ADR-0172 §2 binds "the value's capacity to admit, never the
> persistence of its bytes", and a half that verifies against nothing is not a class
> member in a live position.

**Keeping the attribute and keeping the honesty about it is ADR-0168 §6's own
correction, and it survives this decision unchanged.** That section records a draft
that required no persistent expiry "so that closing the browser ends it", and the
round that found it wrong: a browser configured to restore its previous session
carries both the cookie and the origin's storage across a close, and the gateway —
still running — admits it. So the attribute is right to send and the guarantee is
wrong to rest on. What follows for a page is the awkward truth that closing the
browser *may* end the session and may not, depending on a setting the gateway cannot
see, and the only honest surface for that is a sentence saying so.

**Which is why the obligation here is on the page rather than on the mechanism.**
The alternative was to make the outcome deterministic — clear the header half on
`pagehide`, so that a restored browser finds nothing. It was rejected: it makes the
page enforce a lifetime ADR-0168 §6 assigns to the gateway alone, it breaks the
reload case the milestone is actually about, and it would be a guarantee resting on
a browser event, which is the same class of mistake one event later.

**Re-entry is not a fault and must not be rendered as one.** #1429's survey found
one fault slot at the foot of a thirteen-panel page; a session that ended
legitimately is not an error condition, and putting it in that slot teaches an owner
to read the slot as noise. This is ADR-0083's ruling 4 read at the page: the owner
should learn *what happened and what to do*, and what to do is mint.

### 7. The page re-arms what it announces, and re-issues nothing else of its own motion

> **Normative.** The page may re-establish a **delivery stream** (ADR-0175 §4) of
> its own motion, and only on an event: the document becoming visible
> (`visibilitychange`), or the browser reporting the network reachable (`online`).
> It may not re-establish one on a timer, on a schedule, or on the failure itself.

> **Normative.** A re-establishment the page makes of its own motion is
> **announced** in the page — the attempt and its outcome both, visible without an
> interaction, at the surface the stream feeds rather than only at the page's foot.
> A re-establishment the owner cannot see is forbidden, and no clause of this ADR
> authorises one.

> **Normative.** The page holds at most **one** delivery stream at a time, and
> re-establishes one only while it holds none — one the gateway ended with ADR-0175
> §4's terminal value, or one whose connection failed. An event arriving while a
> stream is open re-establishes nothing.

> **Normative.** After a re-establishment fails, the page does not attempt another
> until one of §7's two events occurs again or the owner acts. A page may not
> convert an event-driven re-arm into a retry loop.

> **Normative.** The page re-issues **no other request** of its own motion. Every
> request that asks the assistant for something — each of ADR-0177 §6's operations —
> is re-issued only on an act by the owner, and that act's outcome is announced in
> the page the same way.

> **Normative.** No re-establishment resumes anything. An answer stream that was cut
> is not resumed and its partial text is not left standing as an answer; ADR-0175
> §10 and ADR-0173 §13 decline resumption and this ADR does not supply it. The page
> re-asks only when the owner asks it to.

> **Normative.** ADR-0168 §9 binds the gateway unchanged, and nothing here reaches
> it. The gateway still does not retry silently, does not queue, and — ADR-0175 §4 —
> "polls again only when a browser establishes a delivery stream afresh, and retries
> no poll of its own motion". This section decides what the **page** may do and adds
> no obligation to the gateway.

**The ground is that a reconnect really is free, and the reason it is free is the
session.** ADR-0175 §4 states it while abandoning a stalled stream — the cost is "a
reconnect — which is free, because a session outlives its connections" — and the
clause that makes it true is ADR-0168 §6: a session is admitted on two values
presented together, not on a connection, so a closed connection is a reconnect and
not a re-admission (ADR-0168 §8 says the same of an idle one). A page that re-arms
therefore spends nothing at the hub, takes no lease and evicts nobody; ADR-0175 §4
has the gateway hold a poll only while a stream is open, so a re-armed stream is the
only thing that starts one.

**"Announced" is the whole of the permission, and ADR-0168 §9 is why.** That section
forbids the gateway retrying silently because a silent retry turns a transport
failure into a wait the owner cannot see — ADR-0083's ruling 4 failure. A page that
reconnects behind the owner's back reproduces it exactly one layer out, and worse: it
is the layer the owner is looking at. So the permission is conditioned on the thing
that removes the failure rather than on the thing that causes it, and a lane
implementing this cites the announcement, not the reconnect.

**One stream at a time is a condition of the permission and not a tidiness rule.**
ADR-0175 §4 writes each delivery "to **every** delivery stream open at the moment it
returned", so a page holding two streams renders every notification twice, with
nothing in the gateway able to tell that the two readers are one browser — §4
forbids it de-duplicating, and ADR-0168 §3 forbids any per-browser identifier
reaching the hub, so the fan-out has no way to notice. Each stream also holds a
connection against `gateway_max_browser_connections`, which ADR-0174 §8 makes the
gateway's total across both listeners, so a page that opened one per visibility
change would exhaust the owner's own ceiling. A page that re-armed on every event
regardless of what it already held was the first draft of this section, and
architecture review found it on the first round. Keying the permission on holding
none makes the page's own state the thing that gates it, which is a fact it can check
rather than one it has to remember, and the two ends it may observe are the two the
corpus already gives it: §4's terminal value, and a connection that failed.

**Events rather than timers is what bounds it with no figure.** A timer is a rate,
and a rate needs a number, a backoff and a ceiling — three things this decision would
have to name and ADR-0168 §8 would have to hold. `visibilitychange` and `online` are
the owner's own acts and the operating system's own fact; both are bounded by
somebody outside the page deciding something, which is a tighter bound than any
figure and costs nothing to state. The no-second-attempt clause is what stops the
pair being turned into a loop by a page that re-fires its own event.

**And the delivery stream is the only thing re-armed of the page's own motion,
because it is the only request that asks the assistant for nothing.** Re-issuing an
`ask` after a failure the page cannot classify is a turn the owner may already have
had executed — ADR-0168 §9 requires the gateway to distinguish a transport failure
from a request the hub received and declined, but a transport failure *after* the
gateway forwarded is indistinguishable from one before, at the page. ADR-0177 admits
thirty operations to the browser, several of which change the assistant's state, so
a page that retried them would be a page that can duplicate them. Offering the owner
a visible retry costs one control and removes the class.

### 8. What this decides no part of

> **Normative.** This ADR decides no `core/protocols.py` and no `core/types.py`
> surface. A lane implementing it that finds it needs either stops and owes its own
> contract ADR, merged first (golden rule 5, ADR-0015 §5).

> **Normative.** It changes no member of the connect exchange, no frame's encoding
> and no method's arguments or results, so no lane implementing it changes
> `PROTOCOL_VERSION` for it (ADR-0124 §9).

> **Normative.** It adds no operation to ADR-0177 §6's enumeration and reaches none
> of them. The mint act is not a request and is not on the browser surface at all
> (§1), so no thirty-first operation is created and ADR-0177 §6's third clause is
> untouched.

> **Normative.** It decides nothing ADR-0168 §12, ADR-0174 §11 or ADR-0175 §10
> defers that is not named in this section, adds no clause to ADR-0172, and reopens
> no ruling of ADR-0168, ADR-0172, ADR-0174 or ADR-0175 beyond the two supersessions
> §9 records.

**Deferred, by name, each with the condition that fires it:**

- **Transport-layer security and a secure context** (ADR-0174 §7 and §11). Held,
  with its trigger unchanged: it fires when a browser capability the surface
  requires is available only in a secure context, or when voice's first rung (#1318)
  asks for microphone capture. Nothing here needs one — the mint act is not a browser
  capability, and every clause of §7 above uses events and requests a page already
  has over plain HTTP. #1230 records the owner's direction that the hub is long-term
  reachable at a public domain with its own authentication; that is far future,
  nothing is scheduled, and this decision neither designs for it nor forecloses it.
  A public door would bring an authentication story of its own and would make the
  bootstrap value one door among two rather than replacing this one.
- **Resuming a cut answer stream.** ADR-0173 §13 declines it — it "needs durable
  partial-turn state the conversation schema is turn-granular and has none of, and it
  wants the composed answer to be in the episode first (#1314)" — and ADR-0175 §10
  inherits the decline. It fires when #1314 lands and a measured drop rate makes the
  case. §7 above re-asks rather than resumes, which is ADR-0173 §9's behaviour.
- **A durable session and a durable browser credential.** Refused for this milestone
  in §5 rather than deferred again. It fires if an owner needs a browser admitted
  from somewhere other than the gateway's own machine, and it owes a ratified ADR
  reopening ADR-0004 §3, §6 and §7 through ADR-0172 §2's condition.
- **The browser-facing surface's shapes, paths, media types and document.**
  ADR-0168 §12 leaves them to the implementing lane, ADR-0174 §11 and ADR-0175 §10
  leave them again, and this ADR reaches none of them. What §6 and §7 above add are
  obligations about what the page *says* and what it may re-issue, not about how it
  is framed.
- **The page's layout, its fault surface's position, and its behaviour at phone
  width.** Lanes 3 and 4 of #1429. §6 obliges three sentences to exist in the page
  and §7 obliges an announcement to be visible at the surface it concerns; neither
  decides where anything sits.
- **The gateway's other signal dispositions.** This ADR names `SIGUSR1` and nothing
  else. Whether the gateway should install stop dispositions of its own, and what it
  should do with `SIGHUP`, is ADR-0083 §4's question asked of a different process and
  is not decided here.
- **Whether this system's logging carries a retention policy.** ADR-0168 §6 declines
  it as a project-wide question and ADR-0172 §3 keeps it declined; the further mint
  records this decision creates change the volume and not the question.
- **A second gateway on one device.** ADR-0168 §12 leaves it open and ADR-0175 §10
  records one consequence of it; nothing here authorises one and nothing here forbids
  one. Two gateways still contend for one delivery slot (ADR-0131 §2), and each mints
  its own bootstrap values because the act reaches one process.
- **Anything about `tools/` egress, residency or the boundaries.** Unreached, for
  ADR-0172 §7's reason: no value this ADR touches is covered content or reaches an
  egress span, and the fourth boundary ADR-0174 §1 designates is neither moved nor
  widened — a second session crosses it exactly as the first does.

### 9. Classification under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement to be made in this text, naming the clause and
applying ADR-0070 §1's test: would a reader holding only the earlier text now act
differently, or read one of its clauses more widely than it now holds?

**Two clauses are superseded and this change writes both records** — each ADR's
`Status` line and an appended dated note, in the scope named here.

- **ADR-0168 §5's second clause**, "The bootstrap value is exchangeable for exactly
  one session. The exchange consumes it, and after it the gateway mints no further
  session until its process is restarted", **only as to its second sentence**. The
  single-use half is untouched and applied; what is replaced is "mints no further
  session until its process is restarted", by §1's mint act and §2's replacement
  rule. A reader holding only §5 builds a gateway on which the second browser
  milestone 16 asks for is unreachable, which is ADR-0070 §1's first limb.
- **ADR-0168 §5's first clause**, "A gateway process mints one **bootstrap value**
  at start … and discloses it exactly once", **only as to cardinality**. The start
  mint, the entropy and the disclosure channel are applied unchanged; what is
  replaced is "one" and "exactly once", by §1's per-mint disclosure. Same limb: a
  reader holding only §5 refuses to disclose a second value.
- **ADR-0172 §1's third class member**, "the **bootstrap value** a gateway process
  mints and discloses once (ADR-0168 §5)", **only in cardinality**, replaced by §5's
  each-value form. A reader holding only ADR-0172 §1 places a gateway's second
  bootstrap value outside the web-session credential class, and therefore outside
  the ADR-0004 §3 exemption — in breach of a clause it obeys in substance. First
  limb, on a scope word. Nothing else of §1 moves: the class stays closed, no kind
  of value joins it, and its prohibition on widening by resemblance is applied.

**Two dated notes are owed without a supersession, and this change writes both.**

- **ADR-0174 §9** — "One bootstrap value still, one session still — and this is not
  ADR-0168 §5's revisit". Every clause of it stays true *of ADR-0174*: it did not
  relax §5, and it left #1320 and #1329 open. What has changed is the world it
  pointed at — "Milestone 16 is [the revisit], on ADR-0168 §12's own trigger, and
  both issues hold together until then" — so a reader arriving at §9 is entitled to
  learn that the revisit has landed and what it chose. That changes no decision of
  ADR-0174, which is why it is a note rather than a supersession (ADR-0070 §1).
  ADR-0174 §11's fifth deferral is discharged in the same act, with durability
  refused rather than granted.
- **ADR-0175 §10's seventh deferral** — "A second live session, a durable session,
  and several browsers admitted at once" — discharged in the same two directions.
  Nothing of ADR-0175 is falsified: §4's fan-out already writes each delivery to
  every open stream, §7's stream and session bounds are unchanged, and §4's
  poll-on-demand rule is what §7 above relies on. The note records the discharge.

**No record is owed on, examined clause by clause:**

- **ADR-0168 §3's two pre-session exceptions.** Untouched, and §1 adds no third in
  terms: the mint act is not a request, so nothing new is served without a session.
  This is the clause most likely to be assumed away by a reader who skims §1, which
  is why §1 states the prohibition rather than leaving it to follow.
- **ADR-0168 §4, whole.** The session's death with the process, the entropy, the
  constant-time comparison, the process-memory-only table, the continuous
  destruction and the ceiling that refuses rather than evicts are every one applied
  rather than narrowed. §4 is written for a population of sessions and reads
  identically whether that population has one member or eight — the ceiling clause
  in particular is the one #1320 says was "early rather than wrong", and a reader
  holding only §4 implements exactly what §4 above requires.
- **ADR-0168 §5's third and fourth clauses.** The exchange's disclosure rule ("a
  failed exchange discloses only that it failed") is applied three times above — §2,
  §4 and §6 each lean on it — and is not read more widely: it governs what a browser
  learns, and every channel this ADR adds for the owner (§1's disclosure, §4's
  standard-output refusal, §6's record) reaches no browser. The fourth clause, "a
  gateway that cannot disclose its bootstrap value does not start", keeps its subject
  — the value minted at start — and §1 says in terms that it does not reach a later
  mint. That is a scope statement about a clause whose own words are about starting,
  not a narrowing of it.
- **ADR-0168 §6, whole, including the mint record's exemption from the rate bound.**
  The two-value admission, the cookie attributes, the lifetime separation, the
  distinct fault for a mismatched pair, the origin-scoped header half, the four
  request classes, the enumeration of permitted Tier 2 facts and the exclusivity of
  that enumeration are all applied unchanged. The one sentence worth the working is
  "A mint record is not rate-bounded and needs no bound, because §5 permits one mint
  per process life", whose stated **reason** this decision removes. The **obligation**
  is unchanged, and ADR-0070 §1's test is about what a reader acts on: a reader
  holding only §6 writes an unbounded mint record, which is what §1 above wants them
  to write. The ground is now §1's rather than §5's — a mint requires standing at the
  machine that runs the gateway, and a process with that standing can read the
  gateway's memory outright, so it is not the population §6's rate bound exists to
  bound ("a caller able to drive a refusal cannot drive a record per attempt"). The
  ground is restated here so that two conforming gateways do not diverge on it, and
  it is one of the four costs §1 weighs against the loopback path, which **would**
  have obliged the supersession.
- **ADR-0168 §7, §9, §10, §11 and §13.** Untouched. §9 is relied on rather than read
  more widely — §7 above binds the page and says in terms that it adds no obligation
  to the gateway. §13's `VISION.md` argument for ephemeral edge state is applied and
  not extended: one outstanding value and at most `gateway_max_sessions` sessions,
  each bounded in size and age and destroyed continuously, is ADR-0094 §9's
  permission on the same terms §13 argued it, and §5 above records that durable state
  would owe the argument again.
- **ADR-0168 §8's figures table and the Consequences' field count.** No record owed,
  and the reasoning is worth stating because ADR-0174 §9's prose reaches the other
  conclusion. §8's table is not an exclusive enumeration — it carries no clause saying
  the gateway has these fields and no others — and its normative clauses are about the
  fields it names. A reader holding only §8 builds a conforming gateway; they lack a
  figure §8 never promised. The corpus has already settled this in practice twice
  without a record: ADR-0174 §8 added three gateway fields and ADR-0175 §8 added one,
  and neither wrote anything on §8's table or on the Consequences' "ten", ADR-0175 §12
  finding no record owed there while finding one owed on §8's read deadline. So §3
  above states its figure in its own section on ADR-0175 §8's form, ADR-0174 §9's
  contrary paragraph is unmarked prose and binds nothing (ADR-0089 §3), and the
  ordinal in it and in #1329 — "an eleventh `Settings` field" — was already overtaken
  by ADR-0174's own three when it was written. The dated note this change puts on
  ADR-0168 mentions the new field so that a reader of §8 can find it, and asserts no
  supersession of the table.
- **ADR-0172 §2's four replacements, and §6's conditionality.** Applied, and §5 above
  states that (d) is satisfied more strictly rather than less: the bound that earns the
  exemption is the process's life, which is kept, and two further cessation events are
  added to one class member. §6 makes the replacements conditions rather than
  descriptions precisely so that a later design is tested against them; this design
  passes the test rather than needing the clause moved.
- **ADR-0172 §3, §4 and §5.** §3's admission-record replacement is applied — §4 above
  records a ceiling refusal under ADR-0168 §6, which is the record §3's third
  replacement names. §4's ruling that "the act that removes the class is stopping the
  gateway process" is as true after this decision as before, and reaches more values
  without changing: stopping the gateway still ends every session and every outstanding
  value at once. §5's no-record-on-a-successful-read ruling keeps the scope it names,
  because §5 above keeps the process bound its scope turns on.
- **ADR-0172 §7.** Its list of what ADR-0172 decides no part of includes "a durable
  browser credential and a session that survives a restart", which §5 above refuses
  rather than grants, so the deferral is discharged in the direction ADR-0172 §2 was
  written to protect.
- **ADR-0174 §§1–8, §10, §11.** The fourth egress boundary, its transport posture, the
  overlay identity, the two admission facts, what carries over of ADR-0168 §6, the
  `Host` and `Origin` rules, the held secure context and the gateway's own ceilings are
  each applied rather than read more widely. §8's "a session minted through either
  counts against the same ceiling" is the clause §4 above makes reachable, and it is
  taken exactly as written. §10's "the gateway never dials a browser" is untouched and
  reinforced: §7 above has the *page* establish every connection, which is that
  section's own direction rule.
- **ADR-0175 §§1–9, §11, §12.** The stream carrier, the discriminator, the answer
  stream, the fan-out, the acknowledgement, the thirty operations as ADR-0177 replaced
  the five, the response-keyed deadline, the figure and the rendering rule are all
  applied. §7's "an open stream is not use of the session that admitted it" matters
  more with several sessions and is unchanged by that; §4's poll-on-demand rule is
  what makes §7 above's re-arm cost nothing.
- **ADR-0177, whole.** §6's thirty operations are the population §7 above quantifies
  over when it forbids automatic re-issue, and the enumeration is neither widened nor
  narrowed. §8's rule that a credential is entered only on a loopback origin is
  untouched — a bootstrap value is not a credential in that section's sense, it is
  ADR-0172 §1's class, and it is entered on whichever origin ADR-0174 §4 admits.
- **ADR-0131.** §2's one delivery connection per device is untouched: several browsers
  behind one gateway still share one poll, which is ADR-0175 §4's fan-out and not a
  second slot. §2's refuse-rather-than-evict direction is re-affirmed in §4 above at the
  moment it becomes reachable.
- **ADR-0004, ADR-0124, ADR-0125, ADR-0126.** Unreached. Every ADR-0004 exemption this
  decision touches is reached through ADR-0172, which is where it was ruled; no value
  travels through `Secrets` or `SecretStore`; the device credential and the enrolled hub
  identity stay exactly where ADR-0124 §4 and §6 put them; and ADR-0126's own
  supersession of ADR-0004 §6 is neither cited nor widened.
- **ADR-0026.** Its revisit condition fires and no record is owed on it. §3 above
  names a monotonic elapsed-time source for one new figure; ADR-0026's `Clock` is a
  civil-instant contract which that ADR says in terms "should not be stretched to"
  elapsed duration, so naming a different source neither widens `Clock` nor narrows
  it, and no seam of ADR-0026 gains or loses a consumer. A reader holding only
  ADR-0026 acts identically. §3's second clause says in terms that the source is that
  figure's alone, so ADR-0168 §4's session bounds and §8's two session figures keep the
  silence they were ratified with and a reader holding only them acts identically too —
  which is what makes this section's "§4 and §8 unchanged" true rather than asserted.
  Whether they should carry the same sentence is a change to a ratified decision beyond
  this lane's subject and is filed as #1439.
- **ADR-0083 and ADR-0084.** §1 above takes ADR-0083 §4's "a signal that silently does
  nothing is worse than one that is documented as doing nothing" as a principle and
  installs a signal that does something documented; nothing about the hub's dispositions
  moves. ADR-0084 §3's ceilings are untouched.
- **`docs/roadmap.md`.** Milestone 16's line is what this decision serves; the roadmap
  records milestones rather than deciding them, and this change edits nothing in it.

### 10. What the implementing lanes owe

Plural deliberately: #1429 splits this decision across two lanes, and saying which
clause lands where is part of the decision.

> **Normative.** The gateway lane lands §1's mint act, §2's replacement rule, §3's
> figure, §4's single exchange refusal and §4's advisory count on every disclosure,
> in `interfaces/gateway/`, `interfaces/cli.py` and
> `core/config.py`. It adds no `core/protocols.py` or `core/types.py` name, and a lane
> that finds it needs one stops (golden rule 5, ADR-0015 §5).

> **Normative.** The page lane lands §6's three sentences and its re-entry rendering,
> and §7's announced re-arm, in `interfaces/gateway/assets/`. It adds no obligation to
> the gateway and needs no gateway change to satisfy either section.

> **Normative.** The first-run guide states the mint act in the terms §1 names — the
> signal, and where the value appears — so that a stranger admitting a second browser
> follows a document rather than inferring one. No lane substitutes a different act for
> it in prose.

**What the gateway lane owes in tests, named because two of these are easy to omit.**
That a value ceases on each of §2's four events and that a refused exchange discloses
nothing distinguishing them; that the exchange refuses at the ceiling — the one place §4
enforces it, reachable by the ordinary path — and that the mint act does **not**
refuse there but discloses the advisory count instead, which is the pair a lane
carrying the earlier draft in its head would get backwards;
that a value the gateway could not disclose is not minted, that a previously
outstanding value still admits after such a failure — the ordering §1 fixes, and the
one an implementation is most likely to get backwards — and that the gateway keeps
serving; that an exchange presenting an undisclosed candidate is refused, which is
what makes §2's admission invariant true across the interval §1's order creates;
and that `gateway_bootstrap_ttl` is refused at load on a non-positive value,
in the `gt=timedelta(0)` form. The monotonic clause of §3 is pinned the way the
session bounds already are — by driving the injected deferral seam rather than by
moving a clock — so that the test asserts the source the gateway uses rather than
the behaviour of the machine it runs on.

**What the page lane owes is harder to pin and is stated as what it must not do.**
`tests/interfaces/gateway/test_bundle.py` pins bytes rather than behaviour and there is
no front-end test runner (#1383), so the announcement obligation of §7 is not fully
mechanically checkable. What is checkable is the negative: no timer-driven
re-establishment in the bundle, no re-establishment while a delivery stream is
already held, and no automatic re-issue of an ADR-0177 §6 operation.
A lane that can pin only the negative pins the negative and says so, rather than
claiming a check it did not make.

## Consequences

- **A second browser costs a keystroke instead of a restart.** The laptop and the
  phone are admitted at once, which is the arrangement ADR-0174 built the fourth
  egress boundary for and could not complete under ADR-0168 §5. ADR-0168's
  Consequences sentence — "every gateway restart logs every browser out, and a
  second browser needs a restart" — keeps its first half and loses its second.
- **`core` gains one `Settings` field**, `gateway_bootstrap_ttl` (§3), strictly
  positive at load, not nullable. It is contract surface in ADR-0054's sense, as
  ADR-0168 §8's ten and ADR-0175 §8's one already were; it is not `core` Protocol or
  type surface, so golden rule 5 is not triggered and no triad is owed.
- **#1320 and #1329 close with this decision's implementing lane.** The ceiling is
  reachable and refuses at the exchange, the one act that raises the live count; the
  unexchanged value has a clock, an origin and a closed list of what ends it.
- **A notification now reaches every admitted browser at once**, because ADR-0175 §4
  already writes each delivery "to **every** delivery stream open at the moment it
  returned" and there can now be more than one browser holding one. That is the
  behaviour that section chose, arriving in the arrangement it was written for; no
  clause of it moves.
- **`gateway_max_sessions`'s default of 8 becomes a number an owner can hit**, where
  before it was inert. Eight browsers on the owner's own devices is generous for the
  arrangement ADR-0168 §2 and ADR-0174 §2 describe, and an owner who wants a
  different number sets the field.
- **The gateway takes a signal disposition it did not have.** That is one more thing
  a supervisor's configuration can matter to, and one more line in the first-run
  guide — and it is the cheapest form of the act, since the alternative was a listener
  surface (Alternatives).
- **The gateway's platform is stated where it was implicit.** §1 records that this
  system's resident processes already require `AF_UNIX` sockets and asyncio signal
  dispositions, so the mint act asks for nothing the hub does not already ask for.
  That is a fact about the tree made legible rather than a new requirement.
- **What becomes harder:** the page owes announcements it did not owe. Every
  re-establishment is a visible state the layout has to carry, on a page #1429's
  survey already found short of room at phone width. That is deliberate: the
  announcement is the permission, and a lane that finds it inconvenient is looking at
  the cost of the rule rather than at a reason to drop it.
- **What becomes harder, second:** the owner has to be at the machine that runs the
  gateway to admit a browser. That is the same standing ADR-0168 §5 already assumed
  for reading the value, so nothing new is asked of them — but it is now the standing
  the *act* needs, and an owner who runs the gateway under a supervisor whose output
  they cannot read cannot use it. §8 records that as a residual with its trigger.
- **Revisit when** an owner genuinely needs a browser admitted from somewhere other
  than the gateway's machine, which is what would fire the durable credential §5
  refuses; when a measured drop rate makes resuming a cut answer stream worth its
  durable partial-turn state (ADR-0173 §13, #1314); or when the public door #1230
  records arrives, which brings its own authentication and would make the bootstrap
  value one door among two.

## Alternatives considered

- **`assistant gateway mint`, a CLI act reaching the running gateway over
  loopback.** The shape the brief named first, and the one most systems would build:
  the CLI knows `gateway_port` from `Settings`, so it needs no discovery state, and
  the gateway could disclose on its own standard output rather than in the response
  so the caller learns nothing. *Rejected in §1.* It hands every local process and
  every local user the ability to **cause** a mint, which is ADR-0168 §3's amplifier
  reintroduced at the one act §3 exists to protect; it needs a fifth request class
  and a third pre-session exception, superseding two exclusive enumerations
  (ADR-0168 §3 and §6) that are exclusive because an earlier draft's exclusion list
  admitted things nobody intended; it needs its own clause saying it is not served on
  ADR-0174 §2's remote listener, where a signal needs none; and it obliges a rate
  bound on the mint record, because §6's exemption for that record rests on a mint
  being something an arbitrary caller cannot drive. Four costs, against a signal's
  none.
- **A CLI act that sends the signal.** Friendlier than `kill -USR1`, and it was the
  first thing tried. *Rejected in §1*: it has to find the process, and nothing in this
  system tells it which one — a pidfile is durable edge state ADR-0094 §9 would have
  to be argued for, and a port-to-pid lookup is a platform-specific dependency for a
  convenience. The gateway naming the act and its own process id in every disclosure
  buys the same usability with no state and no dependency.
- **A line on the gateway's own standard input.** Elegant: the standing required is
  exactly the standing §5's exposure argument assumes, since the owner is at the
  terminal the value prints to. *Rejected*: a gateway started under a supervisor, or
  with its input closed, has no such channel, and the act would then exist on some
  gateways and not others — the underdetermination ADR-0168 §8's opening refuses. A
  signal reaches both.
- **`SIGHUP` rather than `SIGUSR1`.** *Rejected in §1*: `service/hub.py` already
  installs `SIGHUP` as the explicitly ignored signal on ADR-0083 §13's "a restart is
  the reload", so the corpus already means something else by it — and a terminal
  hangup delivers it, which would mint a live admission ticket every time an owner
  closed a window.
- **Several outstanding bootstrap values at once.** Would let an owner mint one per
  device before walking anywhere. *Rejected in §2*: it is a pool with no bound, so it
  needs a ceiling figure and a refusal of its own, and each member is a live admission
  ticket in the scrollback. Replacement gives the owner one invariant a guide can state
  in a sentence.
- **Refuse to mint while a value stands, rather than replacing.** Safer-sounding.
  *Rejected in §2*: it fails in the case the act is most often reached in — the owner
  mistyped and wants another — and it makes the outstanding value a thing they must
  first learn how to cancel.
- **Say the bound is ADR-0168 §5's and no clock is owed** (#1329's first option).
  Genuinely arguable while §5 stood, because one value per process life *is* a bound.
  *Rejected in §3*: this decision removes the half of that pair which did the bounding.
  Values are now minted on demand, so "until the process exits" is a bound only on the
  process, and a gateway that runs for weeks would hold a live ticket for weeks.
- **Relate `gateway_bootstrap_ttl` to `gateway_session_ttl` at load.** *Rejected in
  §3*: ADR-0168 §8 relates two bounds on the same object because one above the other
  can never bind. These bound different objects, both orders are coherent, and a check
  would assert a relationship neither figure claims — ADR-0175 §8's refusal of a
  cross-figure check, for the analogous reason.
- **Refuse the mint act at the ceiling, or refuse at both doors.** The first two
  drafts of §4, and the shape that reads as obviously right: tell the owner where they
  are standing. *Rejected in §4.* Refusing at both leaves the exchange branch
  unreachable, which is #1320's own defect reintroduced by the decision closing it;
  refusing only at the mint act spreads one invariant across two moments and, once §1
  orders disclosure before promotion, admits an interleaving in which the old value is
  exchanged during the disclosure and the candidate promotes past a ceiling that
  refused it. Repairing that needs either an event loop blocked on a write to a
  back-pressured pipe or a refusal of a value already on the owner's screen. Printing
  the count as advice costs neither.
- **Tell the browser the ceiling was hit.** *Rejected in §4*: ADR-0168 §5 requires a
  failed exchange to disclose only that it failed, and a ceiling refusal that named
  itself would hand any local process a probe for how many browsers the owner has
  admitted. The record carries it to the owner instead.
- **Evict the oldest session at the ceiling.** *Rejected*, on the ground ADR-0168 §4
  and ADR-0131 §2 already give: it hands a silent lever for logging the owner out, and
  the eviction looks like an ordinary expiry. Making the ceiling reachable is exactly
  the moment that argument stops being hypothetical, so it is re-affirmed rather than
  re-opened.
- **A durable session, or a durable browser credential the owner types.** The other
  reading of "session persistence", deferred here by ADR-0168 §12, ADR-0174 §9 and
  ADR-0175 §10. *Rejected in §5*: it is a second Tier 0 secret with human-chosen
  entropy, it reopens ADR-0004 §3, §6 and §7 through ADR-0172 §2's condition, it owes
  ADR-0168 §13's `VISION.md` argument on durable edge state, and nothing in milestone
  16's exit test asks for it once re-entry costs a keystroke.
- **Clear the header half on `pagehide`, so closing the browser deterministically
  ends the session.** *Rejected in §6*: it assigns a lifetime to the page that
  ADR-0168 §6 assigns to the gateway alone, it would be a guarantee resting on a
  browser event — the mistake §6 already corrected once — and it breaks the reload
  case, which is the half of "persistence" that already works.
- **Let the page retry on a timer with backoff.** The conventional design. *Rejected
  in §7*: a rate needs a figure, a backoff and a ceiling, and the events available
  (`visibilitychange`, `online`) are bounded by somebody outside the page deciding
  something, which is tighter than any number and needs none. A timer is also the
  shape that is easiest to make silent, and silence is what ADR-0168 §9 forbids.
- **Let the page re-issue a failed assistant request automatically, announced.**
  *Rejected in §7*: at the page a transport failure before the gateway forwarded is
  indistinguishable from one after, so an automatic re-issue can duplicate a turn the
  assistant already ran. ADR-0177 admits thirty operations, several state-changing.
  The owner's own click costs one control and removes the class.
