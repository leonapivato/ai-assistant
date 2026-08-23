# 177. The browser's control surface is thirty operations, and a credential is entered only on a loopback origin

- Status: Partially superseded by ADR-0178 (§8's four-member rendering clause, and §8's no-claim clause, each only as it reaches a surface rendering a `Confirmation` that carries ADR-0178 §1's egress member)
- Date: 2026-08-22
- Amended: 2026-08-24 by ADR-0186 — **§1's third clause, by a count and nothing
  else.** That clause reads that `learn` "is the one operation of the promoted
  surface that is neither in the enumeration above nor the gateway's own". The
  change carrying this note adds `recent_decisions` and `export_decisions` to
  `AssistantEngine` (ADR-0186 §1), so there are now **three** such operations and
  the word "one" is false. Under ADR-0070 §1's test a reader acts identically: the
  obligation that clause imposes is that no lane puts `learn` in a browser without
  its own ratified decision, and that is untouched — as is §1's *first* clause, an
  explicit closed enumeration ("exactly these **thirty** … and no others") which
  governs any method it does not name. ADR-0186 §6 states the same conclusion for
  these two in terms: neither is one of the thirty, no browser request resolves to
  either, and the gateway makes neither call of its own. **The count of thirty is
  itself unchanged**, because it counts what a browser may reach and not what the
  promoted surface carries.

  The note lands on the change that adds the methods rather than in ADR-0186's own
  authoring commit, which ADR-0186 §13 places and argues as a departure from
  ADR-0184 §11: this sentence counts methods on the promoted surface and stays
  **true** until a method lands, so a note written when that document merged would
  have had ADR-0177 disclaim a state of the world that had not happened yet.
- Partially superseded: 2026-08-22 by ADR-0178 — **two sentences of §8, and the
  precondition beside them is discharged rather than replaced.** ADR-0178 is the
  decision §8's precondition names (#1366), and it discharges it on **its own
  ratification and merge**: it adds one member to
  `Confirmation` carrying the connected account's identity and the binding's payload
  description, derives ADR-0148 §2's canonical destination set from it, and makes the
  member's absence the discriminator §8's second limb asked for. Clause by clause,
  under ADR-0070 §1's test — would a reader acting on the sentence act differently?

  **Replaced — §8's rendering clause, only as it reaches a surface rendering a
  `Confirmation` that carries that member.** "A browser turn that parks renders the
  parked action from the `Confirmation` the turn returned, carrying all four of its
  content members — `tool_id`, `tool_description`, `parameters` and `reason` — and
  answers it by relaying `token` to `resume`." The count is now five, and a reader
  holding only this sentence builds a browser prompt that omits the recipients — the
  thing ADR-0148 §8's last sentence says is not a confirmation of an egress call.
  ADR-0178 §8 replaces it with *all* of the confirmation's content members, and its
  §7 states what the new one owes. Everything else this clause says — that the
  rendering is from the returned `Confirmation`, and that the answer relays `token`
  to `resume` — is unchanged.

  **Replaced — §8's no-claim clause, on the same scope.** "**The surface does not
  claim that what it rendered is ADR-0148 §8's confirmation content.**" It was
  written for a surface that could not have the content; a surface rendering
  ADR-0178 §7's floor has it, and refusing to say so would understate the
  confirmation to the user. **Its three sub-clauses are not replaced and bind
  unchanged**: the rendered arguments are still not the canonical destination set, a
  flat destination among the parameters is still not a canonical one, and a
  connected account the surface was not given is still one it may not name.

  **Discharged, not replaced — §8's precondition.** "No lane ships a browser surface
  that answers a confirmation before a ratified decision supplies what ADR-0148 §8's
  fourth clause requires … or supplies a discriminator…" ADR-0178 supplies both, and
  a clause naming the event that ends it is not amended by that event — the
  treatment §12 of this ADR itself gave ADR-0151 §14 ("satisfied rather than
  relaxed"), and ADR-0083 §15's own test. **The block on the browser confirmation
  surface lifts when ADR-0178 is ratified and merged, and not while it stands
  `Proposed`** — §8's gate turns on a *ratified* decision, and ADR-0178 §8 says so in
  its own clause.

  **Not replaced — everything else in §8, and every other section.** The opaque
  token, `resume` answered with `approved` alone, insertion as text through the
  document's own text node, `parameters` rendered whole, `pending_confirmations` as
  the one recovery route, and §8's closing statement that *this* ADR decides no part
  of ADR-0148 §8's fourth clause — all stand as written. §1's enumeration of thirty,
  §3's hop ruling, and §§4–12 are untouched.
- **§11's first deferral is discharged by the decision it names.** "ADR-0148 §8's
  fourth clause — what a CONFIRM on an egress call puts to the user… #1366 holds it,
  and the lane that takes it owes a decision on whether the account identity, the
  canonical destination set and ADR-0150's spans reach the adapter as members of
  `Confirmation` or as a separate promoted read, and on what a
  `pending_confirmations` recovery carries when the trail holds only a digest."
  ADR-0178 answers all three: members, not a read (its §1); and recovery carries the
  same content the live path carries, because `PermissionDecision.egress_binding` is
  stored whole and the digest bounds only the payload (its §5). A deferral discharged
  by the decision it names is not an amendment of the text that deferred it
  (ADR-0083 §15), so this bullet records the outcome and §11 is unchanged.

- **This is `track:web-client` milestone 15's control-surface decision** (#1230,
  batch #1365). Its exit test is *the leg-11 and leg-12 exit tests (#1081, #1159)
  re-run entirely from the browser*, and two ratified refusals stand between the
  browser and that: ADR-0175 §6's closed enumeration of **five** browser-reachable
  operations, which admits no sixth "without its own ratified decision", and
  ADR-0151 §13's third clause, which keeps the five connection operations off
  every transport but the loopback socket "before a ratified decision rules the
  credential's hop". This decision is the one both clauses name.
- **No implementation lands with it.** No `src/`, no `tests/`.
- **It decides no `core/protocols.py` and no `core/types.py` surface** (§11), so
  golden rule 5 is not triggered. It adds **no** `Settings` field and moves no
  figure (§9), so it is not contract surface in ADR-0054's sense either — the
  position ADR-0172 was in, rather than ADR-0168 §8's, ADR-0174 §8's or ADR-0175
  §8's.
- **It partially supersedes one ADR, in one clause, and that record rides this
  change** (ADR-0070 §1, ADR-0082 §1, ADR-0083 §15): **ADR-0175 §6's first
  clause**, "A browser request resolves to calls on exactly these **five**
  operations of the promoted engine surface and no others". A reader holding only
  §6 builds a gateway that refuses twenty-five operations this ADR admits, which
  is ADR-0070 §1's first limb. §6's second and third clauses are used as given and
  are what authorises this: the third says in terms that a lane adds an operation
  *with* its own ratified decision, and this is that decision.
- **Two further records ride this change and are amendments rather than
  supersessions**, in ADR-0070 §1's second limb — a dated header note on ADR-0151
  and one on ADR-0168, each recording that a deferral has been discharged by the
  milestone the deferral itself names. Neither ADR's decision changes and §12
  shows the working.
- **Its required review set is adversarial *and* architecture.** It fixes a closed
  enumeration of the promoted surface a browser reaches and rules a Tier 0
  credential's path, which is the pair ADR-0168, ADR-0174 and ADR-0175 each took
  both lenses for, and `CONTRIBUTING.md` makes a change contract-surface when it is
  the ADR deciding that surface.
- **One consequence can move this milestone and is named up front.** ADR-0148 §8's
  fourth clause — that a CONFIRM on an egress call names the connected account's
  identity, the canonical destination set in both forms, and the payload description
  — **is met by no surface in this tree, the command line included**, and cannot be
  met from `Confirmation`'s five members. This ADR may not close that, because
  closing it is `core/types.py` (golden rule 5); what it does instead is **refuse to
  authorise a second instance of the breach**. §8 places a named precondition: the
  operations are decided and may be built, and **no lane ships a browser surface
  that answers a confirmation** until a ratified decision supplies §8's content or a
  discriminator. #1366 holds that decision. Milestone 15's exit test waits on it, and
  §8 says why that is the right way round.
- **Every reference below to ADR-NNNN is to its text as merged on 2026-08-22**,
  the durability form ADR-0100 established. Refs #1230, #1365.

## Context

### What milestone 15 asks for, and what already answers most of it

Milestone 15 reads, in `docs/roadmap.md` and on #1230: "**15 — control surfaces.**
Sources and grants (grant, amend, revoke); beliefs, questions, answer, observe,
forget; connections plus the CONFIRM prompt for actuator sends." Its exit is *the
leg-11 and leg-12 exit tests re-run entirely from the browser* — which is
`VISION.md`'s "in control: inspect, correct, restrict, delete" promise reaching a
surface a person can actually get to, since today every one of those verbs is at a
terminal.

**Almost nothing here is a new capability.** Every operation the milestone names is
already on `AssistantEngine`, already crosses the wire, and already has a command
line driving it — `grantable_sources` / `grant` / `revoke` / `recent_grants` /
`standing_grants` (ADR-0139), `beliefs` / `belief` / `forget` (ADR-0073),
`questions` / `interrupted_questions` / `answer` / `forget_question` (ADR-0078),
`observe`, `pending_confirmations` / `resume` (ADR-0052), the notification review
five (ADR-0130), and the connection five (ADR-0151). What is missing is a
*surface*, and what stands between the surface and the operations is two ratified
refusals and a set of clauses written over "a surface" whose only reader so far has
been a terminal.

So this decision is not a contract, a transport or an admission scheme. It is the
enumeration ADR-0175 §6 left closed, plus the rulings that make a browser's version
of each surface obey clauses that were written before a browser existed.

### The tree's browser edge, checked rather than remembered

`interfaces/gateway/server.py` serves a closed map of request shapes,
`_ASSISTANT_PATHS`, holding six entries — `converse`, `converse_streaming`, the
delivery stream, `recent_conversations`, `conversation`, `forget_conversation` —
beside the bootstrap exchange and three bundle assets. `RequestClass` in
`interfaces/gateway/records.py` holds four members and is described in its own
docstring as total and fixed in advance. `_TURN_BUDGET` is a module constant of
sixty seconds with exactly two uses, both `timeout=` arguments to a turn call, and
its comment says why it is not an eleventh `Settings` field: "a turn budget is the
*caller's* budget (ADR-0029 §4) rather than one of the gateway's resource bounds."

Nothing in the gateway package mentions `resume` or `pending_confirmations` except
prose recording that they are milestone 15's. There is no path today by which any
`SecretValue` reaches the gateway from a browser.

`AssistantEngine` carries **thirty-two** methods. Five are ADR-0175 §6's,
`next_notification` is the gateway's own poll under §6's second clause, and
twenty-six are unreached. This decision admits twenty-five of them.

### Two hops, not one — where a credential actually travels

ADR-0151 §13's third clause is the refusal this milestone has to get past, and it
is worth quoting rather than paraphrasing, because it is written about a hop that
is not the one a browser creates:

> **No lane exposes these operations over any transport other than ADR-0084 §1's
> loopback socket** — in particular not over ADR-0124's remote listener — before a
> ratified decision rules the credential's hop from an enrolled device to the hub.

A credential typed into a browser takes **two** hops, and only the second is the
one §13 governs.

- **Hop A, browser to gateway.** Either the gateway's loopback listener (ADR-0168
  §2) or ADR-0174's separately configured remote browser listener. §13 has no
  opinion about it, because when §13 was written there was no browser and the
  gateway did not exist.
- **Hop B, gateway to hub.** Either ADR-0084 §1's `0600` loopback socket or
  ADR-0124's remote listener. This is exactly §13's subject, and the refusal is
  built as well as written: `wire/server.py` holds `CONNECTION_METHODS` and closes
  a connection carrying one of the five on the remote listener, and
  `wire/client.py`'s `_refuse_off_loopback` raises before the credential is
  revalidated, unwrapped or put on a socket.

ADR-0174 §11 saw the gap between them and filed it rather than closing it: "**A
gateway dialling its hub over loopback does not meet that refusal**, and no lane
may read the deployment choice this ADR permits as having lifted milestone 15's
inheritance or decided anything about it." ADR-0175 §6 then held the line with a
clause instead of a mechanism. So the question this ADR inherits is not "may the
five be exposed" but "on which of four combinations of two hops", and the two hops
have different protections and different failure modes.

### What ADR-0174 already established about the browser's leg, and the half it withheld

ADR-0174 §2 takes ADR-0124 §2's transport posture whole for the browser leg: the
payload is encrypted end to end between the two devices with no third party holding
a key. §7 then names, precisely, what that does **not** buy:

> What is missing is that **the browser does not know it**: a page served over
> `http://` from an address that is not loopback is not a "potentially trustworthy
> origin", so the browser marks it insecure and withholds the capabilities it gates
> on that classification. Loopback got the classification for free and nobody had to
> notice.

That sentence is a fact about browsers, not a preference, and it decides more of
this ADR than any argument in it. It also comes with §7's own refusal of the
workaround: a self-signed certificate "trains the owner to click through a warning,
which is a habit worth more than the capability."

### What ADR-0148 §8 asks of a CONFIRM, and what `Confirmation` carries

ADR-0148 §8's fourth clause is the content rule for an egress confirmation:

> What is put to the user for a `CONFIRM` on an egress call names the connected
> account's **identity** (§6), the canonical destination set in both forms (§2),
> and the payload description (§6). It names neither the connection reference nor a
> credential slot […] A confirmation that names the tool and not the recipients is
> not a confirmation of an egress call.

`Confirmation` in `core/types.py` carries five members and forbids extras:
`tool_id`, `tool_description`, `parameters`, `reason`, `token`. `tool_id` and
`tool_description` come from the `ToolDefinition` embedded in the recorded ruling;
`parameters` is `turn.plan.steps[0].parameters`, the driven step's own arguments;
`reason` is the policy's, and `ThresholdActionPolicy.decide` states in its own
docstring that "no rule here consults" the parameters, so "**nothing derived from a
payload reaches the `reason` a user is shown**".

Everything §8's fourth clause names lives somewhere else. The connected account's
identity is `BoundAccount.identity` on `EgressBinding`; the canonical destination
set is `EgressBinding.canonical_destination_set`, a derived property; the payload
description is `EgressBinding.spans`. `EgressBinding` hangs off `ActionRequest` and
`PermissionDecision` — and `PermissionDecision` is precisely what ADR-0042 §6 says
the adapter may not read, which is why `Confirmation` exists at all.

**So ADR-0148 §8's fourth clause is unmet at every surface this system has.**
`interfaces/cli.py`'s `_render_confirmation` prints the tool, its description, the
parameters as bare `key = value` lines, and the reason. The flat destination the
user typed appears there incidentally, as an argument value; the canonical form,
the protocol tag and the account do not appear at all. That is the state a browser
inherits, and it is stated here rather than discovered by lane 3, because it looks
from inside milestone 15 like a browser problem and is not one.

### An honest statement of what this ADR is not allowed to settle

It may not change `core`. It may not decide #692's export surface, which has no
engine method at all. It may not reopen ADR-0174 §7's scheme question, whose
trigger it is instead obliged to respect. And it may not close the CONFIRM-content
gap above, because the only shape that closes it is members on `Confirmation`.

## Decision

We will admit **twenty-five** further promoted operations to the browser, keeping
the enumeration closed at **thirty**; keep ADR-0151 §13's refusal on the
gateway-to-hub hop whole and unamended; admit credential entry **only** where the
page's own origin is loopback; bind ADR-0139's, ADR-0073's and ADR-0148's
surface clauses at the browser edge; and add no figure and no `Settings` field.

### 1. Thirty operations, and the enumeration stays closed

> **Normative.** A browser request resolves to calls on exactly these **thirty**
> operations of the promoted engine surface and no others: ADR-0175 §6's five —
> `converse`, `converse_streaming`, `recent_conversations`, `conversation`,
> `forget_conversation` — together with `grantable_sources`, `grant`, `revoke`,
> `recent_grants`, `standing_grants`; `beliefs`, `belief`, `forget`; `questions`,
> `interrupted_questions`, `answer`, `forget_question`; `observe`;
> `pending_confirmations`, `resume`; `notifications`, `dismiss_notification`,
> `forget_notification`, `notification_preferences`,
> `set_notification_preferences`; and `connect_account`, `reprovision_account`,
> `disconnect_account`, `connected_accounts`, `recent_connection_acts`.

> **Normative.** ADR-0175 §6's second clause binds unchanged: `next_notification`
> is the gateway's own poll, no browser request resolves to it, no browser
> argument reaches it, and it is not one of the thirty.

> **Normative.** `learn` is **unreached** from a browser by this decision and is
> the one operation of the promoted surface that is neither in the enumeration
> above nor the gateway's own. No lane adds it without its own ratified decision,
> which is ADR-0175 §6's third clause applied to what this ADR leaves out.

> **Normative.** Every operation admitted above is reached with the arguments the
> promoted surface declares and with no others. Every argument expressing what the
> **user** asked for is the browser's own: the gateway derives none of them,
> defaults none of them, composes no operation out of two, and synthesises no
> result from a call it did not make. ADR-0168 §1's biconditional binds each of the
> thirty exactly as it binds the five.

> **Normative.** The one class of argument the gateway supplies of its own is a
> **caller-owned deadline** — the argument ADR-0029 §4 makes the caller's rather
> than the callee's, and which a browser therefore has no standing to choose. On
> this surface the class has exactly two members: the turn budget given to
> `converse`, `converse_streaming` and `resume` (§9), and the budget given to
> `next_notification` (ADR-0175 §8). No lane widens it by resemblance, and no
> browser value reaches either.

> **Normative.** This ADR creates no principal, no grant and no per-browser scope,
> and no operation above is conditioned on which browser asked. ADR-0099 §1's
> single principal is untouched and ADR-0175 §6's fourth clause binds unchanged:
> every browser the gateway admits is the owner, and a browser reaches exactly what
> the gateway's own device reaches and no more — **which §3 makes narrower for two
> operations than it is for the other twenty-eight**, on the browser's own origin
> rather than on who is asking.

**Twenty-five is derived rather than chosen, and the arithmetic is stated so a
reader can check it.** `AssistantEngine` carries thirty-two methods. Five are
ADR-0175 §6's; one, `next_notification`, is the gateway's own under §6's second
clause; one, `learn`, is left out for the reason below. Thirty-two less those two
non-browser members leaves thirty, and thirty less the five already admitted is
twenty-five. Every method of the promoted surface is therefore on exactly one side
of this section, which is the property an enumeration has and a rule about what is
forbidden does not.

**The deadline carve-out is a fact about the shipped gateway before it is a rule,
and an earlier draft of the clause above forbade it.** `Gateway._ask` already calls
`converse(utterance, timeout=_TURN_BUDGET, conversation_id=conversation)` and the
delivery fan-out already calls `next_notification(budget=gateway_notification_budget)`
— so a flat "derives no argument the browser did not supply" would have been false of
milestone 13's gateway on the day it was written and would have made §9's own ruling
unimplementable. Adversarial review found it. The class is closed at two rather than
left as an exception, because the reason a deadline is exempt is not that it is
convenient: ADR-0029 §4 makes a deadline the *caller's* to set, the gateway is the
caller, and a browser choosing one would be a client setting a bound on a hub's work
— which is a resource question, not a request.

**The enumeration stays an enumeration for ADR-0168 §6's own reason, restated by
ADR-0175 §6 and not weakened here.** "Naming what may appear is the only form that
stays right when a later lane adds a request shape nobody has thought of yet" — and
the surface is still growing. Widening it to thirty does not make the form less
necessary; it makes the residual smaller and the next addition cheaper to spot.

**Leaving `learn` out is a decision and it is the one most likely to be read as an
oversight, so it is argued rather than listed.** ADR-0073 §6 is titled "Correcting
is `learn`; inspection adds no second correction path", and `VISION.md`'s promise
this milestone serves is "inspect, correct, restrict, delete" — so a belief surface
with no `learn` looks like three of four. It is not, because **correcting already
reaches the browser**: `converse` has been in the enumeration since milestone 14,
and telling the assistant it is wrong in a conversation is the path ADR-0162 rules
is recorded. What `learn` adds is an *explicit* door for a `FeedbackEvent` the
caller constructs, and that door is a surface question — what a browser puts in a
`FeedbackEvent`, and whether a form that authors one is a correction or a second
way to assert a belief — that milestone 15's exit test does not ask and this
decision has no consumer for. It is deferred by name in §11 with its trigger rather
than admitted quietly, because an operation admitted without a surface argument is
the accident this enumeration exists to prevent.

**Nothing here is a new capability, and that is the reason the list can be this
long in one decision.** Each of the twenty-five is a ratified operation with a
ratified surface contract and a shipped command-line consumer; what the sections
below decide is the handful of places where "a surface" written for a terminal
means something different in a page.

### 2. The four request classes do not become five

> **Normative.** ADR-0168 §6's enumeration of four request classes is untouched.
> Every request admitted under §1 "asks the assistant for something" in §6's own
> words and is therefore `assistant-request`; no lane adds a fifth class, and no
> lane conditions any rule on which of the thirty an `assistant-request` names.

> **Normative.** ADR-0168 §6's exclusive record enumeration binds unchanged, with
> ADR-0174 §3's one addition standing as that ADR wrote it. No record this decision
> reaches carries an operation name, an argument, a belief, a question, a grant, a
> notification, a connection reference, an account identity, or a credential.

**This is ADR-0175 §12's precedent applied, and it is applied rather than
re-argued.** That section refused a fifth class for the delivery stream on the
ground that "a fifth value would supersede an enumeration that says every request
is 'of exactly one class, out of four' while buying no rule the four cannot carry."
Twenty-five operations do not change that arithmetic: they are twenty-five more
request shapes in one class, and the class exists to say what a record may name,
not to name a route.

**The second clause matters more here than it did for milestone 14, because the
payloads got more sensitive.** A record naming the operation would put "the owner
revoked the calendar grant at 11:04" into the structured stream, which is a Tier 1
fact about the user's own decisions in a record ADR-0168 §6 restricted to Tier 2 by
name. The enumeration already forbids it; the clause is written because twenty-five
new shapes is exactly when somebody adds a field "for debugging".

### 3. The credential's hop, ruled in two legs

> **Normative.** ADR-0151 §13's third clause binds **whole and unamended** on hop
> B, the gateway's own connection to the hub. A gateway reaches the five connection
> operations only over ADR-0084 §1's loopback socket; `wire/server.py`'s
> `CONNECTION_METHODS` refusal and `wire/client.py`'s `_refuse_off_loopback` are
> untouched, and no lane implementing this decision weakens, bypasses or
> conditionalises either.

> **Normative.** A gateway that reaches its hub over ADR-0124's remote listener
> serves **none** of the five connection operations to any browser, on either
> listener. It refuses such a request on a condition of its own, reported as its own
> condition and never flattened into an absent path, an expiry, a ceiling refusal or
> a fault attributed to the hub.

> **Normative.** On the gateway's loopback listener (ADR-0168 §2), all five
> connection operations are admitted, `connect_account` and `reprovision_account`
> included.

> **Normative.** On ADR-0174's remote browser listener, `disconnect_account`,
> `connected_accounts` and `recent_connection_acts` are admitted, and
> `connect_account` and `reprovision_account` are **not**. The gateway serves no
> request shape reaching either on that listener, and a request for one is refused
> on a condition of its own — reported as its own condition, naming that credential
> entry is available on a loopback origin only, and never flattened into an absent
> path.

> **Normative.** The refusal above is decided from the listener the request
> arrived on and from nothing the browser asserts — not from a header, an origin
> value, a body field, or a device identity. It is not lifted by ADR-0174 §4's
> admission, by a device appearing in `gateway_remote_browser_devices`, or by any
> configuration this ADR does not name.

> **Normative.** No lane reads this section as ruling the hop ADR-0151 §13 names.
> The credential's hop **from an enrolled device to the hub** is untouched,
> undischarged, and stays refused; what is ruled here is the hop from a browser to a
> gateway that is itself on the loopback socket.

**The decisive fact is ADR-0174 §7's, and it is mechanical rather than
architectural.** A page served from `http://127.0.0.1:8422` is a potentially
trustworthy origin and a page served from `http://100.x.y.z:8422` is not, whatever
tunnel the second one is inside. On the first the browser gives the owner every
protection it has for a secret: the credential manager is available, the password
field behaves as one, and no interstitial says the form is unsafe. On the second the
browser withholds all of it and tells the owner, correctly, that the page is not
secure — and the owner's only way to proceed is to type a Tier 0 integration
credential into a form their own browser is flagging. **That is the habit ADR-0174
§7 refused to buy with a self-signed certificate, arriving by a different route and
costing the same thing.** The overlay's encryption is real and §2 is not doubted
here; what is missing is the half §7 already named as missing, and a credential
field is the single place in this whole surface where that half is load-bearing.

**Splitting the five rather than refusing all of them is the ruling this section
turns on, and the split is exactly the credential.** `connect_account` and
`reprovision_account` are the only two operations on the promoted surface that take
a `SecretValue` (ADR-0151 §6, first clause: "No other operation on any surface
accepts one"). The other three carry a reference, and a reference is a minted,
opaque value ADR-0151 §3 designed so that it is not a credential. Refusing all five
off loopback would be conservatism applied to the wrong noun — it would deny the
owner a connection *listing* on their phone for a reason that is about a password
field — and admitting all five would put the credential where §7 says the browser
cannot protect it. The split is available because the surface is five separate
operations rather than one, which is the property ADR-0151 §1 chose it for.

**Hop B stays refused because nothing in milestone 15 is evidence about it.**
ADR-0151 §13 asks for a decision on a credential crossing from an *enrolled device*
to the hub — a hop with a different producer, a different admission rule
(ADR-0124 §4's two facts), and a different failure mode. A gateway co-resident with
its hub supplies no evidence about that hop at all, and a decision that lifted it
here would be ratifying a seam with no implementation contact. What this section
does instead is state the arrangement under which milestone 15's exit test runs, and
leave §13's own question exactly where §13 put it.

**What this costs the owner is real and is not smoothed over.** Connecting an
account from a phone is not available in milestone 15. Connecting one *from a
browser* is — on a loopback origin, which on the deployment ADR-0174 permits (a
gateway on the hub's own machine) is the same machine the command line already had
to run on. So the browser gains nothing the terminal had and loses nothing either,
and the exit test's connect step is reachable from a browser exactly as the roadmap
asks. Whether a browser on another device gets it is ADR-0174 §7's trigger to fire,
not this decision's to force.

### 4. What a browser owes the credential it carries

> **Normative.** The credential travels in the body of the request that performs
> the act and nowhere else. It is placed in no URL, no query string, no fragment,
> no path segment, no cookie, no response body, no value the gateway writes on a
> stream, and no browser storage of any kind — neither the storage ADR-0168 §6
> scopes the session's header half to, nor any other.

> **Normative.** The field a browser sends it under is named `credential`, so
> `core/logging.py`'s key-name redaction reaches it wherever a payload mapping is
> logged. No lane renames it, aliases it, or nests it under a key redaction does
> not reach — ADR-0151 §6's second clause, applied to a request field as it was
> applied to a parameter name.

> **Normative.** The gateway relays the credential to the promoted operation's
> `credential` argument and does nothing else with it: it does not log it, retain
> it beyond the call, copy it into any other value, retry a call with it, place it
> in an admission record (§2), or read it back. This is ADR-0151 §6's
> `orchestration` clause applied one hop out, and the gateway acquires no standing
> over the value by carrying it.

> **Normative.** The front end presents no credential field on a page whose own
> origin is not loopback, and never presents one it knows the gateway will refuse.
> A surface that asked for a secret in order to discover it could not be used would
> be disclosing it to obtain a refusal, which is the failure `interfaces/cli.py`
> avoids by opening the engine before it prompts.

> **Normative.** The identity is rendered, and the user's confirmation of it taken,
> **before** the credential field is presented — ADR-0151 §5's rendering obligation
> at this surface, and for its own reason: a credential pasted into an identity
> field is caught only if the identity is shown before the secret is asked for.

> **Normative.** No response to any of the five connection operations carries the
> credential or any value derived from it, and no lane adds a read-back. ADR-0151
> §6's first clause already forbids it on the promoted surface; the clause is
> restated because a browser form's natural behaviour is to redisplay what was
> submitted.

**Every clause here is an existing rule reaching a new surface, and the one that is
genuinely new is the fourth.** The command line's protections are stated over the
things a terminal leaks — argv, the shell's history, a `ps` listing — and its module
docstring is explicit that there is deliberately no `--credential` option for
exactly those three durable disclosures. A browser leaks in different places: a URL
is written to history and to the referrer, `localStorage` outlives the tab, a form
that repopulates on back-navigation holds the value after the page has apparently
gone. So the prohibitions are re-stated against the new leaks rather than
transcribed, and ADR-0168 §5's own posture for the bootstrap value — "not in a log
record, not in an error, not in a response body, and not in any URL a browser
transmits to a server" — is the shape they take.

**The gateway's admission records need no new clause and it is worth saying which
one already covers them.** ADR-0168 §6 makes a record carry *only* the enumerated
Tier 2 facts and forbids "no request body" by name, so a credential cannot reach a
record without the record already being in breach. §2 restates the enumeration
rather than adding to it.

**The fourth clause is where a well-meaning front end goes wrong.** The tidy design
is one connection page that works everywhere and reports a failure if the gateway
refuses — which asks the owner to type a Tier 0 secret into a non-secure page and
*then* tells them it was pointless. The credential has already been typed, already
been in the page's memory, and possibly already been offered to a password manager
that declined to help. So the refusal has to reach the surface before the field
does, which makes the front end's own origin a thing it must read.

### 5. Show-then-confirm reaches a browser, and the browser's showing is structural

> **Normative.** ADR-0073 §5's ceremony binds `forget` at this surface: the browser
> renders the belief it is about to destroy, carrying ADR-0073 §4's fields, and
> takes the user's answer before calling `forget`.

> **Normative.** The render that ceremony rests on is taken from a `belief` read
> issued immediately before the confirmation is offered, and never from an entry of
> a `beliefs` listing the page rendered earlier. A page holds its listing until it
> is navigated away from, so a listing is not a read taken "as late as it can be"
> in ADR-0073 §5's sense, and a browser is the first surface where the difference is
> unbounded.

> **Normative.** ADR-0073 §5's band-appropriate warning binds: the surface says
> that destroying an asserted belief is permanent, and that destroying a derived or
> attested one removes the belief and not its origin, and represents a deletion as
> neither more final nor less final than it is.

> **Normative.** What the confirmation covers is stated at this surface as ADR-0073
> §5 states it — consent to forget the belief that id names, not a guarantee that
> the bytes destroyed are the bytes rendered — and no browser wording claims
> otherwise.

> **Normative.** `forget_question` carries the ceremony at this surface. The
> browser renders the question it is about to destroy, from a `questions` or
> `interrupted_questions` read issued immediately before the confirmation, and takes
> the user's answer before calling `forget_question`. It sends `forget_question`
> only for a question that read returned.

> **Normative.** `forget_conversation` carries the ceremony at this surface, on
> ADR-0073 §5's ground and on that ground alone. No lane may cite the ceremony as a
> protection against ADR-0168 §6's origin-resident-script residual, and no lane may
> cite ADR-0175 §6's residual paragraph as relieving it.

**The `forget_question` ruling is #495's third reason failing to reach a browser,
and #495 is cited rather than absorbed.** #495 records the CLI's omission as a
judgement call resting on three grounds, of which the third is decisive and
surface-specific: "A ceremony needs a read the façade does not have […] a
single-question read is not among [the four façade methods]. Adding one is
unrequested contract-adjacent surface, which slice 2 declined to invent." That
ground is true and this decision does not touch it — **no single-question read is
added, and none is needed here**, because the two list reads ADR-0078 §8 already
gives return the question whole. A terminal takes an id as an argument and must
resolve it; a browser's forget originates from an item it is displaying, and
re-reading the list immediately before the confirmation is a call it already makes.
So the browser can meet ADR-0073 §5 with the façade as it stands, which is the
condition #495 says was missing.

**#495 stays open on its own terms and is not answered by this.** Its actual
question is general — "either ADR-0073 §5's ceremony generalises to anything holding
the user's words, or it is specific to *beliefs* and this verb is correctly outside
it" — and this decision answers neither limb. It rules one surface's behaviour on
the ground that that surface can afford the ceremony, which is a weaker claim than
either. Nothing here changes `assistant forget-question`, and a lane that wants to
must take #495's question rather than cite this section.

**The `forget_conversation` clause reconciles two texts that read as though they
collide, and the reconciliation is mechanical rather than a matter of weighing
them.** ADR-0175 §6's rationale says "A front-end confirmation before a forget is
not a control and is not required here", which sounds like a ruling against the
ceremony. It is not one, for two independent reasons. First, ADR-0175 is a **marked**
ADR and that sentence is **unmarked prose**, so under ADR-0089 §3 it supplies no
obligation at all: in a marked ADR "unmarked text is read to determine what a marked
clause *means* and never supplies an obligation", and there is no marked clause of
ADR-0175 §6 about a confirmation. Second, and independently, the two texts are about
different questions. ADR-0175 §6's sentence is about a confirmation as a *security
control* against the origin-resident script ADR-0168 §6's residual describes, and it
is right: a script that can issue requests the browser will authenticate is not
stopped by a dialog. ADR-0073 §5's ceremony is about *consent* — "a person cannot
consent to destroying something they were not shown" — and a script defeating it says
nothing about whether the person was shown. So the ceremony binds as consent, and
this section forbids the citation in each direction so that a later lane cannot use
one to discharge the other.

### 6. The grant surface at the browser edge

> **Normative.** ADR-0139 §3's five clauses bind this surface as written. They are
> stated over "a surface" and "a client", and a browser is one; no clause of them is
> read as CLI-specific, and none is re-derived here.

> **Normative.** Where the browser offers the user a choice of uses, it carries all
> three members of `GrantScope` — `FACET`, `INGEST`, `NOTIFY` — named in words
> rather than by member name, and offers no proper subset of them. Where it renders
> an existing grant, it renders exactly the uses that grant names.

> **Normative.** A rendering of an existing grant does not display the members the
> grant leaves out, in any form — greyed, disabled, unchecked, struck through, or
> otherwise present-but-negated. ADR-0139 §3's third clause forbids presenting a
> partial scope as incomplete or provisional, and a control that shows all three
> states beside a grant naming one is that presentation made out of a layout.

> **Normative.** No view presents a source's configuration state as part of a
> grant, and no view presents a grant as a statement about whether a source is being
> read. A page that renders `grantable_sources` beside `standing_grants` keeps the
> two questions visually and textually separate, and answers neither with the other.

> **Normative.** No view presents a record from `recent_grants` as live or as
> withdrawn on its own, and no view presents `recent_grants` as the answer to what
> the user currently authorises. `standing_grants` is what states that, and a view
> that has not read it says the state is unread.

**The third clause is ADR-0139 §3's trailing sentence turned into something a
browser lane can fail.** That sentence names the hazard exactly — "A view that
renders a `FACET`-only grant as `FACET` and then greys out `INGEST` and `NOTIFY`
beside it is presenting the user's decision as a half-filled form" — and a checkbox
group is the single most natural control for a three-member scope. So the clause is
written at the level of the widget rather than the level of the principle, because
the principle was already ratified and the widget is what a lane builds.

**The fourth clause is where a browser is more exposed than a terminal, and the
reason is layout rather than wording.** A command line answers one question per
invocation. A page shows several at once, and a "Sources" screen that lists what can
be granted next to what is granted next to whether anything is configured is the
obvious information architecture and the one ADR-0139 §3's fourth clause forbids: it
conducts a conversation about configuration where the user is deciding about consent,
which ADR-0093 §7 exists to keep apart. The clause does not forbid one page; it
forbids one *answer* being read off the other.

### 7. An amendment is two browser requests, and its third outcome is the browser's own

> **Normative.** Amending a grant is composed **client-side**, in the front end, as
> ADR-0139 §4's two acts in order — `revoke`, then `grant` — carried by two separate
> browser requests resolving to two separate engine calls. The gateway serves no
> request shape that performs both, composes no amendment, and holds no state
> between the two; a gateway that did would be composing behaviour the promoted
> surface does not offer, which ADR-0168 §1 forbids.

> **Normative.** The surface reports the outcome of **each** act as one of
> ADR-0139 §4's exactly three: it landed, it is known not to have landed, or its
> outcome is not known. It never reports an incomplete amendment as merely failed,
> and never presents an amendment as atomic or as leaving the source continuously
> granted.

> **Normative.** Which of the three an act gets is read from ADR-0168 §9's
> distinction and from nothing else: a request the hub received and declined is
> **known not to have landed**; a transport failure between the gateway and the hub
> is **not known**. ADR-0168 §9 already obliges the gateway to make a browser able
> to tell those two apart, and this is what that distinction is for.

> **Normative.** A failure of the **browser's own** request to the gateway — the
> request was sent and no response was read — is an outcome that is **not known**,
> whatever the gateway did. It is a third producer of ADR-0139 §4's third outcome
> that no earlier surface had, and no front end resolves it by assuming either of
> the other two.

> **Normative.** Where the revocation's outcome is not known, the front end does
> **not** send the grant. It reports the revocation as not known, leaves the
> amendment incomplete, and infers no state from the unresolved act.

> **Normative.** The user's decision about the new scope is taken **before** the
> revocation is sent, and the revocation is sent only for a source the user has
> decided a new scope for. No surface revokes in order to ask.

> **Normative.** A page that goes away between the two acts is ADR-0139 §4's
> cancellation limb at this surface: the amendment is incomplete, the source's state
> is unread, and the surface asserts nothing about it. On its next load the surface
> reads `standing_grants` and renders what that returned, and states no state it has
> not read.

> **Normative.** No surface infers the source's current grant state from either
> act's outcome, at any point in the flow. In particular a refused `grant` is not a
> statement that the source is ungranted, and a landed revocation is not one either.

**Composing it in the front end rather than in the gateway is ADR-0139 §4's own
reasoning arriving one hop out.** That section explains why a client composes the
two calls: "composing them client-side is what puts the intermediate state where a
surface can report it, which is the whole of the second clause." A gateway route that
did both would put the intermediate state back inside a process the user cannot see —
the same defect the refused `amend(source, scope)` engine method has, rebuilt at a
different layer, and forbidden a second time by ADR-0168 §1.

**The fourth clause is the one this surface adds, and it is added because the
browser is two hops from the store rather than one.** `interfaces/cli.py`'s
`_outcome_of` classifies a `TransportError` as unknown and a typed `AssistantError`
as known-not-landed, because the CLI holds the socket itself and those two exhaust
what can happen. A browser holds no socket to the hub: between it and the store sit
its own request, the gateway, and the gateway's wire connection, and its own request
can fail after the gateway has already called. ADR-0085 §8e's residual — a mutating
call committed by the hub whose response was lost — therefore has a second instance
here, and a front end that treated a failed `fetch` as "it did not happen" would
assert exactly the thing ADR-0139 §4 spends five clauses refusing to let a surface
assert.

**The page-went-away clause is where ADR-0139 §4's cancellation limb has to be
re-stated rather than inherited, because the mechanism is different and the escape
is not.** ADR-0139 §4's fifth clause is about `CancelledError` and about a cancelled
surface not starting a call in order to report. A page that is closed does not report
at all — there is nobody to report to, and no `except` clause runs. What survives is
the *prohibition*, which is what ADR-0139 §4 already identified as the invariant: "the
state is never inferred from the unresolved act, and where this surface cannot read
it, the user's next call can." A page's next load is that next call, and the clause
names it so that a front end does not restore a hopeful local view of what it thinks
it granted.

### 8. The CONFIRM prompt is decided and its surface is blocked until ADR-0148 §8 can be met

> **Normative.** **No lane ships a browser surface that answers a confirmation
> before a ratified decision supplies what ADR-0148 §8's fourth clause requires** —
> the connected account's identity, the canonical destination set in both forms and
> the payload description — **or supplies a discriminator by which a surface can
> refuse an egress confirmation it cannot render.** `pending_confirmations` and
> `resume` are in §1's enumeration and may be built and tested; no installation
> reaches a browser confirmation until that decision merges. This is a named
> precondition on the implementing lane, in the form ADR-0021 §3, ADR-0097 §9a,
> ADR-0149 §8 and ADR-0151 §13 use.

> **Normative.** No lane cites this ADR, its enumeration, or the readiness of an
> implementation as satisfying that precondition, and no lane narrows it to
> non-egress confirmations on its own authority. A surface cannot tell an egress
> confirmation from any other from `Confirmation`'s members, which is why the
> precondition reaches confirmations whole and why a discriminator discharges it.

**Everything below states what that surface owes when it is unblocked**, so that
the decision is taken once and the lane that builds it is not writing a second ADR.

> **Normative.** A browser turn that parks renders the parked action from the
> `Confirmation` the turn returned, carrying all four of its content members —
> `tool_id`, `tool_description`, `parameters` and `reason` — and answers it by
> relaying `token` to `resume`.

> **Normative.** The browser's answer supplies `resume`'s `approved` argument and
> nothing else. `timeout` is the caller-owned deadline §1 and §9 place with the
> gateway, and no browser value reaches it.

> **Normative.** The `token` is relayed **opaquely**. The front end parses no part
> of it, derives nothing from it, renders it nowhere, and stores it in no browser
> storage; the gateway mints none, rewrites none and substitutes none. It is
> ADR-0042 §4's continuation and this surface is a relay for it.

> **Normative.** Every value the `Confirmation` carries is inserted into the page as
> text through the document's own text node, never as markup and never through any
> interface that parses markup. `Confirmation`'s own contract states that its values
> are carried "as data, not pre-formatted" and that escaping is each adapter's job;
> ADR-0175 §9's rendering clause is that obligation for this adapter and is not
> relaxed for a parameter value.

> **Normative.** `parameters` is rendered whole — every key and every value the
> mapping carries — and the surface omits none, truncates none silently, and orders
> none in a way that hides one. A confirmation showing some of the arguments a call
> would run with is not a confirmation of that call.

> **Normative.** `pending_confirmations` is the surface's recovery read and is used
> as ADR-0052 §1 designed it: a browser renders each recovered confirmation before
> the user answers it, and answers each through `resume` with its own token. A
> browser that has been closed and reopened, and a gateway that has been restarted,
> both recover through this read and through no other route.

> **Normative.** **The surface does not claim that what it rendered is ADR-0148 §8's
> confirmation content.** It does not describe the rendered arguments as the
> canonical destination set, does not present a flat destination appearing among the
> parameters as a canonical one, and does not name a connected account it was not
> given. ADR-0073 §4's floor is the form of this obligation — a surface "must not
> present a derived belief as carrying a warrant it cannot show" — applied to a
> confirmation.

> **Normative.** This ADR does **not** decide ADR-0148 §8's fourth clause and no
> lane cites it, or the floor above, as having met it. The floor is what the surface
> owes **in addition to** the precondition, never in place of it.

**A floor alone was this section's first draft and adversarial review was right to
refuse it.** ADR-0148 §8's fourth clause requires a CONFIRM to name the connected
account's identity, the canonical destination set in both forms, and ADR-0150's
payload description. `Confirmation` carries none of the three:
`BoundAccount.identity`, `EgressBinding.canonical_destination_set` and
`EgressBinding.spans` all hang off `EgressBinding`, which lives on
`PermissionDecision` — the value ADR-0042 §6 forbids an adapter to read, and the
reason `Confirmation` exists. So a browser answering an egress confirmation would let
the owner authorise a send **without being shown the recipients**, which §8's own last
sentence calls out by name: "A confirmation that names the tool and not the recipients
is not a confirmation of an egress call." That the command line does the same thing
today is a fact about a breach that exists; it is not a licence for a decision to
authorise a second instance of it. **A ratified floor is not weakened by being
unmet** — an ADR admitting a new surface to it is exactly where that would happen
silently, and this is the document that has to refuse.

**So the precondition, and not a refusal of the operations.** Three shapes were
available. Leaving `pending_confirmations` and `resume` out of §1 would mean a second
ratified decision later, re-opening an enumeration this one exists to settle. Admitting
them with a floor alone is the breach above. Admitting them and blocking the *act* is
the shape the corpus already uses for exactly this — ADR-0151 §14: "The five operations
may be built and tested; a connection may not be provisioned in an installation until
#909 lands." The contract is decided once, nothing is built against a shape that will
change, and the thing that waits is the thing that would otherwise be wrong.

**What it costs is milestone 15's exit test, and that is stated rather than
discovered.** #1159's item 5 puts exactly one CONFIRM in front of the user and asks
them to approve a real send, so re-running it entirely from the browser needs this
surface. Under this section the exit test waits on #1366's contract decision. The
alternative was an exit test passed by a surface that ADR-0148 §8 says is not a
confirmation of an egress call, which is a worse thing to have passed.

**The gap is not milestone 15's and that is checkable rather than asserted.**
`interfaces/cli.py`'s `_render_confirmation` prints the tool, its description, each
parameter as `key = value`, and the reason — `Confirmation`'s four content members and
nothing else. The terminal that ran #1159 met §8's fourth clause no better than a
browser would. What milestone 15 changes is that the gap acquires a second surface and
a decision that has to look at it, which is why #1366 exists and why the precondition
above is the answer rather than a note.

**The claim clause is the whole of what this section protects.** A browser rendering
`to = alice@example.com` beside a heading that says "recipients" would be asserting
that the user is looking at the bound canonical set, when what they are looking at is
the argument the model produced before binding — and ADR-0148 §14 names reconstruction
of a supplied form from a canonical one as a failure in terms. The floor permits the
rendering and forbids the assertion, which is exactly the shape ADR-0073 §4 chose for
a citation it could not resolve.

### 9. `resume` rides the turn budget, and no figure is added

> **Normative.** `resume` is given the same budget a turn is given at this surface.
> No `Settings` field is added for it, no second figure is introduced, and no lane
> reads this decision as moving, promoting or re-defaulting the gateway's turn
> budget.

> **Normative.** ADR-0175 §7's response-keyed read deadline covers a `resume`
> exactly as it covers a `converse`: a connection carrying a response the gateway
> has not finished writing is not idle, so `gateway_read_timeout` does not close a
> connection carrying an outstanding `resume`.

> **Normative.** ADR-0168 §8's figures are untouched by this decision, and its
> ceiling arithmetic is unchanged: every operation §1 admits is served on a hub
> connection counted against `gateway_max_hub_connections` exactly as a turn is.

**One figure and not two, because a resumed turn is a turn.** `resume` continues a
parked step and returns a `TurnOutcome`; the work it does after the answer is the
same work `converse` does before parking. A second number would be a second claim
about one fact and the two disagreeing has no defensible reading, which is ADR-0084
§3's argument against a second length member and the one ADR-0175 §8 used against a
separate heartbeat.

**Not promoting the constant is deference rather than an omission, and the constant
says so itself.** `_TURN_BUDGET` carries its own reasoning in place: "It is a
constant rather than an eleventh `Settings` field on purpose… a turn budget is the
*caller's* budget (ADR-0029 §4) rather than one of the gateway's resource bounds.
Whoever measures that a browser needs its own buys the field." Milestone 15 has
measured nothing, so it buys nothing. A lane that finds a resumed egress call
routinely exceeds sixty seconds has the measurement that clause asks for, and the
field is a `Settings` addition it may then propose — which is ADR-0054 surface and
its own small decision, not a side effect of admitting an operation.

**Whether the figure should be a setting is a separate question and this ADR takes
no position on it.** The clause above binds `resume` to whatever the turn budget is,
so promoting the constant later changes both together and needs no amendment here.

### 10. The notification review surface, and dismissal is not acknowledgement

> **Normative.** The five review operations reach the browser as §1 admits them, and
> what they operate on is the notification **record** (ADR-0130). Nothing on this
> surface acknowledges, retires, withdraws or completes a **delivery**.

> **Normative.** ADR-0175 §5's third clause binds unchanged: a `delivery_id` never
> reaches a browser, is placed in no value the gateway writes on a stream, in no
> response body, in no document and in no URL, and no browser request carries one.
> No lane reads `dismiss_notification` or `forget_notification` as a route by which
> one could.

> **Normative.** No surface presents dismissing or forgetting a notification as
> affecting whether it was delivered, and none presents having received a delivery
> as affecting the record's disposition. They are two acts on two objects and the
> surface says so.

> **Normative.** `set_notification_preferences` is a read-modify-write and the
> surface treats it as one: it sends the whole `NotificationPreferences` value it
> read, renders what the call **returned** rather than what it sent, and states no
> preference state it has not read back.

> **Normative.** A notification's content rendered on this surface is
> engine-supplied text, neutralised exactly as a reply is (ADR-0175 §9), and is
> rendered with no warrant it does not carry — ADR-0099 §4's floor and ADR-0073 §4's
> before it bind a notification's summary and detail here as they bind them on a
> delivery stream.

**The first three clauses exist because ADR-0175 §10 predicted this exact
confusion.** That section deferred the review surface to milestone 15 and named the
hazard while doing it: "Dismissal in particular is a judgement about the notification
*record* (ADR-0130), which is a different act from the delivery acknowledgement §5
keeps inside the gateway, and conflating them is the mistake this deferral exists to
prevent." A browser that now sees notifications arrive on a delivery stream *and*
holds a list it can dismiss from is the first place both objects are on one screen,
so the deferral's own warning is turned into clauses rather than inherited as prose.

**The fourth clause is the read-modify-write hazard a page has and a command has
not.** `set_notification_preferences` takes and returns a whole
`NotificationPreferences`, so a surface that renders its own optimistic view after a
call — or that sends a value assembled from a form it filled from a read taken some
time ago — can silently revert a preference. Rendering what the call returned is the
same discipline §7 applies to a grant: an act's outcome is a fact about that act, and
the state is a fact the hub states.

### 11. What this decides no part of

> **Normative.** This ADR decides no `core/protocols.py` and no `core/types.py`
> surface. A lane implementing it that finds it needs either stops and owes its own
> contract ADR, merged first (golden rule 5, ADR-0015 §5).

> **Normative.** It changes no member of the connect exchange, no frame's encoding,
> and no method's arguments or results, so no lane implementing it changes
> `PROTOCOL_VERSION` for it (ADR-0124 §9).

> **Normative.** It adds no clause to ADR-0130, ADR-0131, ADR-0139, ADR-0148,
> ADR-0151, ADR-0168, ADR-0172, ADR-0173 or ADR-0174, reopens no ruling of any of
> them, and decides nothing they defer that is not named in this section.

**Deferred, by name, each with the condition that fires it:**

- **ADR-0148 §8's fourth clause — what a CONFIRM on an egress call puts to the
  user.** Unmet at every surface, and closable only with structural members on
  `Confirmation`, a promoted read of the binding, or a discriminator — all
  `core/types.py`. **It is not merely deferred: §8 makes it a precondition on the
  implementing lane**, so the browser confirmation surface does not ship until it
  lands. #1366 holds it, and the lane that takes it owes a decision on whether the
  account identity, the canonical destination set and ADR-0150's spans reach the
  adapter as members of `Confirmation` or as a separate promoted read, and on what a
  `pending_confirmations` recovery carries when the trail holds only a digest.
- **`learn` from a browser** (§1). Fires when a surface argument exists for what a
  browser puts in a `FeedbackEvent` — whether an explicit correction form is a
  correction or a second way to assert a belief, and how it relates to the
  correction path `converse` already carries. Nothing here forecloses it.
- **The credential's hop from an enrolled device to the hub** — ADR-0151 §13's own
  question, untouched (§3). It fires on a producer for that hop, which is a remote
  *client*, not a browser; a gateway co-resident with its hub supplies no evidence
  about it.
- **`connect_account` and `reprovision_account` from a browser on another device**
  (§3). Fires with ADR-0174 §7's own trigger — a transport-layer security
  arrangement for the remote browser listener — which is the thing that makes the
  page a secure context and the browser's own protections available to a credential
  field. Nothing here forecloses it and nothing here reaches for a certificate.
- **Export** (#692). It has no engine method at all, so it is not an operation this
  enumeration could admit; it owes its own contract ADR, and `VISION.md`'s
  "*Export*'s missing interface" is what it answers.
- **The operator and admin read surface**, hub-owned intent routing, and the hosted
  plane. `docs/roadmap.md` holds all three as stated-not-scheduled, and none is a
  milestone-15 exit.
- **Operating-system notifications and every other secure-context browser
  capability.** ADR-0174 §7's stop condition stands whole and ADR-0175 §9's in-page
  clause is unchanged; the owner's ruling of 2026-08-21 on #1230 is about
  milestone 14's exit test and is not widened here.
- **A durable session, a second live session and several browsers admitted at
  once.** ADR-0168 §5 and §12 defer them to milestone 16, ADR-0172 §2 makes the
  process-lifetime bound a condition of three exemptions, and ADR-0174 §9 and
  ADR-0175 §10 each decline to be that revisit. #1320 and #1329 hold until then.
- **The request shapes, paths, framing and media types** for everything §1 admits.
  ADR-0168 §12's division is unchanged: they are not `core` surface, they are not a
  Protocol, and the front end and the gateway ship and version in one distribution
  (ADR-0168 §10). This ADR fixes which operations are reachable and what their
  surfaces owe, and nothing about the bytes.
- **Whether the gateway's turn budget should be a `Settings` field** (§9). Fires on
  a measurement, which the constant's own comment already names as the price of the
  field.

### 12. Classification under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement to be made in this text, naming the clause and
applying ADR-0070 §1's test: would a reader holding only the earlier text now act
differently, or read one of its clauses more widely than it now holds?

**One clause is superseded and this change writes the record** — ADR-0175's `Status`
line and an appended dated note, in the scope §1 names.

- **ADR-0175 §6's first clause**, "A browser request resolves to calls on exactly
  these **five** operations of the promoted engine surface and no others". A reader
  holding only §6 builds a gateway on which twenty-five of the thirty operations §1
  admits are unreachable, and would refuse a request for one as a request the surface
  has no shape for. That is ADR-0070 §1's first limb — a reader acting differently —
  and the replacement is §1's enumeration of thirty. **Nothing else of §6 moves.** Its
  second clause (`next_notification` is the gateway's own sixth), its third (every
  other operation unreached, and no lane adds one without its own ratified decision)
  and its fourth (no principal, no grant, no per-browser scope) are used as given, and
  the third is the authority under which this ADR acts rather than a clause it
  displaces: it contemplates exactly this decision and requires it.

**Two amendments are recorded and neither changes a decision**, in ADR-0070 §1's
second limb — an ADR reconciled with a fact that postdates it, such that a reader
acting on it acts identically before and after. Both ride this change as appended
dated header notes.

- **ADR-0151** gains a note recording that §13's third clause is **undischarged and
  unamended**, and that ADR-0177 §3 rules a different hop. A reader holding only §13
  keeps every operation off every transport but the loopback socket, which is exactly
  what §3's first clause requires of a gateway; §3 adds no route around it and §11
  restates its question as standing. The note exists because a reader arriving at §13
  after this milestone would otherwise have to work out for themselves whether a
  browser is a transport, and ADR-0174 §11 already recorded that the gap is easy to
  lose.
- **ADR-0168** gains a note recording that §12's fifth deferral — "**Account
  connection from a browser on another device**", inherited by milestone 15 — is
  discharged by the milestone it names. Its answer is §3's: refused, with ADR-0174
  §7's trigger named. A deferral discharged by the milestone that deferral names is
  not an amendment of the text that deferred it, which is ADR-0083 §15's own test and
  the treatment ADR-0175 §12 gave three of §12's deferrals; the note records the
  outcome rather than changing §12.

**No record is owed on:**

- **ADR-0168 §1's biconditional.** Used as given, and §1's fourth clause is it
  restated. Every one of the twenty-five admitted operations is a promoted method the
  gateway calls with arguments the browser supplied and renders the result of; the
  gateway composes nothing, and §7's client-side amendment is the clause that keeps it
  that way at the one place a composition would be tempting. §3's refusals are not a
  narrowing of §1 either: a request the surface has no shape for on a given listener
  falls in ADR-0168 §6's residual fourth class exactly as it does today, and §1's
  biconditional quantifies over the shapes the gateway serves.
- **ADR-0168 §6.** Its four request classes, its exclusive record enumeration, its
  refusal-on-one-condition rule and its two-value admission all bind unchanged (§2).
  §3's two new refusals are refusals on their own conditions in §6's own form; a
  further member of a condition vocabulary is a value of a field §6 already
  enumerates, which is the position ADR-0174 §3's addition was in, and no field is
  added.
- **ADR-0168 §2, §4, §5, §7, §8, §9, §10.** Used as given. One bootstrap value, one
  session per process, the ceiling that refuses rather than evicts, the door checks,
  the ten figures, the fault legibility and the one-distribution rule are relied on
  and none is read more widely. §9 in particular is *used* by §7's third clause rather
  than extended: the distinction it already obliges is what an amendment's three
  outcomes are read from.
- **ADR-0175 §§1–5, §7–§10.** Used as given. §1's carrier is what every admitted
  operation travels on; §2's discriminator and terminal-value rules are unchanged;
  §3's turn clauses are untouched, and §7's response-keyed deadline covers a `resume`
  as §9 above says; §5's `delivery_id` prohibition is restated at §10 rather than
  narrowed; §9's rendering clause binds a `Confirmation`'s members as it binds a
  reply's; §10's deferrals of the review surface and of `resume`/`pending_confirmations`
  are discharged by the milestone they name, and its deferral of a browser-to-gateway
  stream, of multiplexing and of a durable session are restated as standing.
- **ADR-0174 §§1–4, §7, §8, §10, §11.** Used as given, and §7 is used most heavily:
  §3 above applies its stated fact about a non-loopback `http://` origin rather than
  adding one, and respects its stop condition by refusing the capability rather than
  working around it. §11's fourth deferral — "Which of the promoted engine's
  operations a browser may reach" — is discharged by the milestone it names, on its own
  terms. §4's admission is untouched and §3's refusal is explicitly not keyed on it, so
  the device list stays a door policy and does not become a permission input (#920).
- **ADR-0151 §§1–12, §14–§18.** Used as given. The five operations, their signatures,
  the minted reference, the three promoted types, the identity rule, the credential's
  single-argument path, the interruption and displacement rules, the disconnection
  report, the two listings and the auditing ruling are all relied on and none is
  changed. §5's rendering obligation is applied at §4 rather than extended. §14's
  precondition is **satisfied rather than relaxed**: #909 was closed by ADR-0153, which
  routes ADR-0126's offline purge through a `ConnectionPurger`, so provisioning is
  unblocked and no clause here is a route around anything.
- **ADR-0139 §§1–8.** Used as given, whole. §2's read, §3's presentation rules, §4's
  two acts and three outcomes, §5's disclosure and §7's trigger ladder bind at this
  surface because they were written over "a surface" and a browser is one. §6 and §7
  above restate them at the level a browser lane builds at and add exactly one thing
  §4 did not have a producer for — a failure of the client's own request to an
  intermediary — which is a new instance of §4's third outcome rather than a fourth.
- **ADR-0073 §§1–10.** Used as given. §4's per-belief fields are what §5 above
  renders; §4's floor is the *form* §8 borrows for a confirmation and is not extended
  to one; §5's ceremony, its band-appropriate warning and its statement of what the
  consent covers bind at this surface unchanged, and its adapter obligation to take the
  render as late as it can is what §5's second clause makes concrete for a page. §6's
  "correcting is `learn`" is untouched, and §1's deferral of `learn`'s browser door is
  not a reading of §6.
- **ADR-0078 §8, §9.** Used as given. The four façade methods are unchanged, no
  single-question read is added, and `forget_question`'s contract is untouched — §5
  rules a surface's ceremony, which ADR-0078 §9 leaves to the surface exactly as
  ADR-0073 §5 does.
- **ADR-0130 and ADR-0131.** ADR-0130's notification record, its dispositions and its
  preference surface are reached and re-judged by nothing here. ADR-0131 §§1–5 are used
  as given: §2's one slot, §2a's claim-and-release, §3's outbox and §4's `delivery_id`
  capability are untouched, and §10 above forbids the one route by which a review
  surface could have reached the last of them.
- **ADR-0148 §§1–14.** Used as given, and §8 is **obeyed rather than read more
  narrowly**. Its fourth clause is unmet in the tree, which is a fact about the tree
  rather than a reading of the clause; §8 above refuses to authorise a surface that
  would repeat the breach, states what such a surface will owe when it is unblocked,
  and forbids the claim it must never make. Nothing here permits an egress call the
  policy would refuse, changes the approver, or lets a surface stand in for one.
- **ADR-0052 §1, §3.** Used as given. `pending_confirmations` is the recovery read it
  was designed as, each recovered confirmation is rendered before it is answered, and
  §8's fifth clause is ADR-0052 §3's own rule at a second surface.
- **ADR-0042 §4 and §6.** Used as given, and §8's floor is what §6 makes necessary: the
  adapter may not read the audit trail or a `PermissionDecision`, which is precisely why
  what `Confirmation` does not carry cannot be recovered by a browser reading harder.
- **ADR-0172.** Untouched. §1's class of three credentials is closed and no fourth is
  minted, held or admitted; the integration credential §4 above carries is the user's
  own value in transit and is neither held by the browser nor stored anywhere in it,
  which is what keeps it outside that class.
- **ADR-0099 §1 and §4.** §1's single principal is used as given and §1 above says so.
  §4's rendering floor is applied to a notification's content at §10 and to a
  confirmation's at §8, which is the floor obeyed rather than extended.
- **ADR-0054.** Not engaged. This decision adds no `Settings` field and moves none,
  which is the position ADR-0172 was in; ADR-0168 §8 added ten, ADR-0174 §8 three and
  ADR-0175 §8 one, and none of those figures moves here (§9).
- **Golden rule 3.** §1's fourth clause, §7's refusal to let the gateway compose an
  amendment, and §2's refusal of a fifth request class are each the rule applied. An
  interface adapter that composed two engine calls into one act, or held state between
  them, would be authoring; each clause is what makes that detectable.

## Consequences

- **`VISION.md`'s "in control" promise reaches a surface a person can get to.**
  Inspect, restrict and delete are in the browser after this; correct is there through
  `converse` and its explicit door is deferred (§1). That is the milestone's whole
  point and the reason twenty-five operations land in one enumeration.
- **The browser surface stops being small.** Milestone 14's gateway serves six request
  shapes; milestone 15's serves those plus shapes for twenty-five operations. The
  implementing lanes are adaptation rather than invention — every operation is built,
  wired and driven from a command line — but the front end roughly quadruples, and
  #1365 cuts it into three lanes for that reason.
- **Connecting an account from a phone is not available**, and that is a named cost
  rather than an oversight (§3). The owner connects from a browser on a loopback origin
  — which on the arrangement ADR-0174 permits is the machine the command line already
  required — and gets everything else in milestone 15 from anywhere on the overlay.
  ADR-0174 §7's trigger is what changes it.
- **The gateway becomes the second place a Tier 0 integration credential passes
  through**, and §4 is the whole of what it may do with it. Nothing is stored, nothing
  is logged, nothing is recorded, and the field name is chosen so that redaction reaches
  it if a payload mapping is ever logged anyway.
- **The browser CONFIRM surface is blocked, and milestone 15's exit test waits with
  it** (§8). ADR-0148 §8's fourth clause has never been met at any surface; rather than
  give it a second unmet one, this decision blocks the act until #1366's contract lands.
  That is a real cost to the milestone's schedule, paid to avoid an exit test passed by
  a confirmation ADR-0148 §8 says is not one. The operations stay in §1's enumeration,
  so nothing is re-decided when the block lifts.
- **What becomes harder:** a thirty-member enumeration is a longer thing to check a
  request against than a five-member one, and the check now has two answers on two
  listeners rather than one everywhere. That is the price of splitting the connection
  surface by whether an operation carries a secret, and §3 argues it is worth paying
  against the alternative of refusing a connection *listing* on a phone.
- **Revisit when** ADR-0174 §7's scheme question is answered, which lifts §3's
  credential refusal; when a contract ADR adds the members ADR-0148 §8 needs, which
  replaces §8's floor with the clause; when a surface argument exists for `learn` (§1);
  or when milestone 16's durable session admits a second browser, which makes §7's
  page-went-away clause and §10's read-modify-write clause reachable by two viewers at
  once rather than by one.

## Alternatives considered

- **Admit all five connection operations on both listeners, on ADR-0174 §2's
  end-to-end encryption.** The tidy answer, and the confidentiality argument is
  genuinely sound. *Rejected in §3*, on ADR-0174 §7's own stated fact rather than on a
  preference: the overlay protects the credential and the browser does not know it, so
  the owner is asked to type a Tier 0 secret into a page their browser is flagging as
  insecure, with the credential manager withheld. That is the habit §7 refused to buy
  with a self-signed certificate, and buying it here would spend ADR-0174 §7's stop
  condition rather than respect it.
- **Refuse all five off the loopback listener.** Symmetric with ADR-0151 §13 and
  simpler to state. *Rejected in §3*: it denies a connection *listing* and a
  *disconnect* on a phone for a reason that is entirely about a password field, and the
  surface is five separate operations precisely so that it can be split (ADR-0151 §1).
  Refusing the two that take a `SecretValue` is the narrowest rule that reaches the
  actual hazard.
- **Rule ADR-0151 §13's own hop discharged, and let a remote gateway carry the five.**
  It would make the deployment story uniform. *Rejected in §3*: §13 asks about a
  credential crossing from an enrolled device to the hub, a hop with a different
  producer and a different admission rule, and a gateway co-resident with its hub is no
  evidence about it. Ratifying it here would bless a seam with no implementation
  contact, which `CONTRIBUTING.md` names as the thing to spike first.
- **Buy the secure context now — an overlay-issued certificate for a MagicDNS name.**
  It would remove §3's split entirely. *Rejected*: ADR-0174 §7 examined it, found it
  workable, and named what it costs — an operating act with a control-plane feature
  behind it, a dependence on names #912 is careful about, and a renewal story. It is a
  real decision with real conditions and it is not milestone 15's; §11 leaves it on §7's
  trigger.
- **Add the members ADR-0148 §8 needs to `Confirmation` in this ADR.** It would close
  a genuine defect where it was found. *Rejected in §8 and §11*: it is `core/types.py`,
  and golden rule 5 puts a Protocol or contract-type change behind its own ratified ADR
  merged before anything implements against it. Deciding it inside a surface ADR would
  be exactly the ordering that rule exists to prevent, and the question is larger than
  a browser — it reaches what a `pending_confirmations` recovery can carry when the
  trail holds only a digest.
- **Ship the browser CONFIRM to a floor, on the ground that the command line is no
  better.** This section's first draft, and the shape adversarial review blocked.
  *Rejected in §8*: ADR-0148 §8's own last sentence says a confirmation naming the tool
  and not the recipients "is not a confirmation of an egress call", so the floor would
  have let an owner authorise a real send without being shown who it goes to. An
  existing breach is a reason to fix it, never a licence for a decision to authorise a
  second instance — and an ADR admitting a new surface is precisely where that would
  otherwise happen quietly.
- **Leave `pending_confirmations` and `resume` out of §1's enumeration until #1366
  lands.** The other way to keep the surface unreachable, and simpler to state.
  *Rejected in §8*: it re-opens the enumeration this decision exists to settle, so
  milestone 15 would owe a second ratified decision for two operations whose surface
  contract is already written here. ADR-0151 §14's shape — decide the operations, block
  the act — costs one clause and no second ADR.
- **Let the browser refuse only *egress* confirmations, and answer the rest.**
  Narrower than blocking the surface, and it would leave most confirmations reachable.
  *Rejected in §8*: `Confirmation` carries no member by which a surface can tell an
  egress call from any other, so the rule is unimplementable without the discriminator
  that is itself part of what #1366 must decide. §8's precondition names that
  discriminator as one of the two things that discharges it.
- **Render the parameters as ADR-0148 §8's destination set anyway, since a
  destination usually appears among them.** It would make the browser prompt read as
  conforming. *Rejected in §8*: the flat form a user typed is not the canonical set,
  ADR-0148 §14 names reconstruction of one from the other as a failure in terms, and a
  surface asserting a warrant it cannot show is the failure ADR-0073 §4's floor was
  written against.
- **Let the gateway serve one "amend" request that revokes and grants.** One
  round-trip, one obvious route, and the front end gets simpler. *Rejected in §7* on
  two ratified grounds at once: ADR-0139 §4 requires the two acts to be composed where
  a surface can report the intermediate state, and ADR-0168 §1 forbids the gateway
  composing behaviour the promoted surface does not offer. It is the refused
  `amend(source, scope)` engine method rebuilt one layer out.
- **Treat a failed browser request as "it did not happen".** The natural front-end
  error path. *Rejected in §7*: the gateway may already have called, so the outcome is
  ADR-0139 §4's third — not known — and a surface asserting either of the other two is
  asserting something it cannot know. ADR-0085 §8e's residual has a second instance at
  this surface and the three-outcome contract already has a slot for it.
- **Admit `learn`, so the browser has all four of `VISION.md`'s verbs explicitly.**
  Tempting, and it costs one more entry in the enumeration. *Rejected in §1*: what a
  browser puts in a `FeedbackEvent` is a surface question milestone 15's exit test does
  not ask and this decision has no consumer for, and correcting already reaches the
  browser through `converse` on the path ADR-0162 rules is recorded. An operation
  admitted without a surface argument is what a closed enumeration exists to prevent.
- **A fifth request class for the control surfaces.** It would let a record
  distinguish a grant change from a turn. *Rejected in §2*: every one of them asks the
  assistant for something and is `assistant-request` in ADR-0168 §6's own words, and a
  record that distinguished them would be carrying a Tier 1 fact about the owner's
  decisions in a record §6 restricts to Tier 2.
- **A `Settings` field for a resume budget.** Symmetric with ADR-0175 §8's addition.
  *Rejected in §9*: a resumed turn is a turn, so a second figure is a second claim about
  one fact, and `_TURN_BUDGET`'s own comment already names the measurement that would
  buy the field. Nothing in milestone 15 has taken it.
