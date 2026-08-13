# 146. Outbound content is classified by its discloser, and provenance never moves a tier

- Status: Proposed
- Date: 2026-08-13
- **Decides a classification and adds no `core` surface.** No Protocol, no type,
  no field. One seam this classification will need — a marker that carries a
  span's discloser provenance to an egress boundary — is deferred in §8 with its
  trigger rather than specified here, on golden rule 5, ADR-0015 §5 and ADR-0073
  §4's "with a producer in hand" standing: nothing at the `tools/` seam
  transmits, so no producer exists whose demands would shape the field.
- **Required review set: adversarial *and* architecture.** **Declared, not
  compelled.** `CONTRIBUTING.md` → "Stop when the required reviews are green"
  makes a change contract-surface when it touches `core/protocols.py` or
  `core/types.py` "**or when it is the ADR deciding that surface**", and by the
  bullet above this ADR decides no surface; `scripts/ship.sh` gates the
  architecture lens on those two files changing and would accept adversarial
  alone. The set is taken anyway, on two grounds: this settles a **security**
  classification, where a second independent lens is worth more than the
  convention's minimum, and it supplies the content of an ADR-0017 §3 condition
  that a later ADR will attest against. Reviewed while `Proposed` and ratified
  only after (`CONTRIBUTING.md` → "Finishing an ADR PR").
- **Filed as #94**, split out of ADR-0017 (PR #72) during a scope cut. Dispatched
  in batch #1096. It **settles** ADR-0017 §3's outbound-payload-classification
  condition and **discharges nothing else**: the seam stays undesignated and the
  other thirteen conditions stand exactly as written. **#75** — warning on an
  apparent secret paste — is out of scope and §7 says why it may not be cited
  toward any clause here.
- **A stacked addition under ADR-0082 §1; no record is owed on ADR-0004 or
  ADR-0017, and none is written.** §10 names the clauses and applies the test to
  each.

## Context

### The problem, in the words of the two ADRs that create it

ADR-0004 §1 classifies by **what a value is**: "Every piece of stored data is one
of three tiers", Tier 0 being "OAuth tokens, API keys, refresh tokens". A user
who pastes an API key into a conversation has put a Tier 0 value into a message.

ADR-0004 §5's safety net cannot see it. That section configures structlog with "a
redaction processor that drops/masks known sensitive keys" — the net is keyed on
**field names**, and a credential inside a free-text message body sits under no
sensitive key at all. ADR-0029 §3 says the same thing about the one field where
the corpus has already met this: `core/logging.py`'s redactor "redacts by *key*",
and its own docstring names `error=str(exc)`, "where the provider quoted the
user's prompt", as the Tier 1 leak it does not see.

So a rule of the form *Tier 0 must not leave the device except as the provider
credential* is violated by every ordinary model call from the moment someone
pastes a key, with nothing able to detect the violation. **A rule that is false on
the day it is written is worse than no rule**, and this is the shape ADR-0098 §6
already refused to buy back with a classifier.

### What ADR-0017 §3 asks for, and why the seam cannot be designated without it

ADR-0017 §3's thirteenth condition is not a deferral. In its own words:

> **Outbound payload classification is settled** (issue #94), including how
> Tier 0 a user typed into a conversation is treated. Without it the tier
> description above is unusable for tool arguments: an implementation could
> classify a pasted OAuth token as Tier 1 because it arrived in conversation,
> pass inspection, and disclose a credential under weaker policy.

ADR-0017 §9 states the standing plainly — "#94 is a §3 condition, not merely
deferred: the seam cannot be designated until it is settled." The condition names
the *other* condition it makes unusable: the payload-description condition, which
requires "the payload bound before transmission and described inspectably after
it — which records, how many, **at what tiers**". So the settlement this ADR owes
is not an abstract taxonomy; it is an answer to *what a payload description says
about a span the user typed*.

### The line drafted in ADR-0017, and where it is weaker

The line ADR-0017 drafted and #94 carries is to classify by **who is disclosing**.
User-authored content is disclosed by the user: authoring a message and sending it
to a provider they configured is one act, and the system is a conduit rather than
a party deciding on the user's behalf. System-assembled context — memory records,
retrieved facts, anything `orchestration` adds that the user did not write into
this message — is decided by the system, so minimisation binds it.

#94 also names where that argument gets weaker, and it is right: at the `tools/`
boundary the user's words may be forwarded to an arbitrary third party rather than
to a provider the user configured. Leg 12 is where tools begin to transmit, which
makes that the sub-question this ADR most owes an answer to rather than a
restatement. §4 answers it, and the answer is not the one the drafted line
implies.

### The neighbouring vocabulary, read rather than assumed

ADR-0098 §1 defines **external content** — "any span of text that this system did
not author and did not receive from its own user" — and rules that membership "is
decided by **recorded origin**, never by inspecting the text". That is the same
discipline this ADR needs, on the inbound axis. The two axes are orthogonal and
this ADR keeps them so: a retrieved calendar record is external (ADR-0098) *and*
system-selected (here); a user's paste is not external — ADR-0098 §1 says so in
terms, "a user who pastes an email into a turn is exercising judgement" — and is
user-authored here; a plan rationale this system's own model wrote is neither
external nor user-authored, and is system-selected.

### What this ADR is not allowed to settle

- **It may not designate the `tools/` seam**, add a condition to ADR-0017 §3's
  list, or relax one. ADR-0124 §1 and ADR-0125 §9 each record declining exactly
  that, and the list is the designating lane's to satisfy.
- **It may not narrow ADR-0021 §6's standing grants or ADR-0017 §3's
  "standing user policy"** in the course of answering the `tools/` question.
  ADR-0098 §3 left the analogous question open by name after architecture review
  found an earlier draft narrowing both while claiming it narrowed neither; §8
  leaves this one open the same way.
- **It may not impose a precondition on `models/`.** ADR-0017 §2 "neither
  re-authorises nor certifies it and adds no precondition to it", and §2's
  reasoning for naming three missing controls rather than fixing them — that
  gating `models/` on them "would prohibit every model call the product runs on"
  — governs here too. §6 states the asymmetry rather than hiding it.
- **It may not claim a detection capability**, and §7 forbids anyone reading one
  into it.

## Decision

Marked under ADR-0089: every obligation this ADR imposes is a marked clause, and
unmarked text supplies none.

### 1. Two questions, not one: what a value is, and who disclosed it

> **Normative.** A value's tier under ADR-0004 §1 is a property of the value. It
> is not changed by who disclosed it, by the medium it arrived in, or by which
> subsystem holds it. No component assigns a span a lower tier on the ground that
> it arrived inside a user's message.

> **Normative.** Every span of content a component prepares for transmission
> across an egress boundary (ADR-0124 §1) has exactly one **discloser
> provenance**: **user-authored**, where the user composed that span into the
> exchange being served, or **system-selected** in every other case — including a
> span this system's own model authored and a span the system retrieved from its
> own stores.

**The two questions were being asked as one, and that is the whole defect #94
describes.** "Is this Tier 0?" is about the value. "Did this system decide to send
it?" is about the act. Collapsing them forces a false choice: either a paste
reclassifies a credential as Tier 1 — which is the laundering ADR-0017 §3 names —
or every model call becomes non-compliant the moment a user pastes a key. Keeping
them apart costs nothing and dissolves both horns. The paste is not reclassified;
it is simply not something the system authorised.

**This is why ADR-0004 §1 is left untouched and this ADR stands beside it.** §1's
sentence is about **stored** data and assigns a tier to a value; extending it to
cover the act of disclosure would be writing a second axis into a ratified
sentence that does not have one, which is a decision change and not an amendment
(ADR-0070 §1). §10 applies ADR-0082 §1's test to that clause and to every other
one this ADR sits beside.

**Provenance is a property of a span, not of a message or a call.** One assembled
prompt routinely carries both: the user's question and the memory records
`orchestration` retrieved to answer it. A rule stated over the call would have to
pick one answer for both, and the interesting cases are exactly the mixed ones —
which is the same granularity ADR-0098 §2 chose for its marking, and for the same
reason.

**Model-authored text is system-selected, and that is the clause that does the
work later.** A model that writes a tool argument has produced a span this system
selected, even where the argument reproduces the user's words. §2 says why that
cannot be undone by comparing the two.

### 2. Provenance is recorded at receipt, carried, and never inferred

> **Normative.** Discloser provenance is decided by **recorded origin**, never by
> inspecting a span and never by matching it against anything the user wrote.

> **Normative.** A span for which no origin was recorded is **system-selected**.

> **Normative.** Provenance is relative to the exchange in which the user composed
> the span. A span the system retrieves from its own stores into a later exchange
> is system-selected in that exchange, whatever it was in the exchange where it
> arrived.

**Recorded rather than inferred is ADR-0098 §1's discipline, and it is here for
the same reason it is there.** ADR-0094 §5's line — "a claim carried in a
submission is not evidence of the standing it claims" — reads on this axis as: a
span cannot earn the user's voice by resembling the user's words. An
implementation that recovered provenance by substring-matching model output
against the user's message would be letting whoever influenced that model choose
the provenance, and would additionally be the detector §7 forbids anyone from
buying a bound with.

**Absent-means-system-selected is the fail-closed direction and is the clause most
likely to be quietly dropped.** The permissive default is attractive because it
makes an unimplemented path work: a lane that has not wired provenance through
gets "user-authored" for free and its payloads stop looking like disclosures.
That is precisely the state in which the rule would be false and unenforceable, so
the default runs the other way — an unmarked span is the system's to answer for.
It is the same shape ADR-0098 §1 chose for its allow-list, where "a source added
later is enrolled in the *protection* by default and must be argued out of it".

**Provenance expires with the exchange, and that is a decision rather than a
detail.** The user composed their message into *this* turn. When `orchestration`
later retrieves that turn's episode into a prompt, the user did not compose
anything; the system chose to include it. Reading provenance as durable would let
one paste convert an arbitrary later transmission into a user disclosure, which is
the transitivity §4 refuses on the recipient axis, taken along the time axis
instead. §7 states what this costs, honestly.

### 3. The surviving claim: system-selected Tier 0 is only ever a credential, to the party that issued it

> **Normative.** No component selects for transmission a span it holds as Tier 0
> to any recipient other than the party that issued that credential.

> **Normative.** A user-authored span is never a route by which this system
> discloses Tier 0 it holds. No component places a value it holds as Tier 0 into
> a span it then classifies as user-authored.

**This is #94's surviving claim, stated so that it is true on the day it is
written and checkable afterwards.** It is keyed on what a component *holds as*
Tier 0 — a recorded classification — and not on what a span contains, because the
second is the unobtainable bound. ADR-0098 §3 records the corpus learning this the
expensive way: three clauses in one section were "stated over something this
system cannot obtain" and were rewritten over what a serialiser and a caller do,
"which is checkable in a test".

**It holds today at all three boundaries ADR-0124 §1 names, which is what makes it
worth ratifying now.** `models/` sends the provider credential to the configured
provider (ADR-0017 §2's declaration of what it transmits). A designated `tools/`
seam would read an integration's credential through `Secrets` (ADR-0004 §3 as
replaced by ADR-0125) and present it to that integration's own upstream. The
remote transport's client presents its enrolment credential to the hub that
enrolled it (ADR-0124 §1's second clause: "sends only two things: the connect
frame §7 requires, and the request it was asked to make"). Everything else the
system selects and sends is Tier 1 or Tier 2. There is no fourth case, and a lane
that finds itself wanting one is looking at a bug.

**The second clause closes the bypass the first would otherwise leave open.**
Without it, a component holding a credential could embed it in the outbound
rendering of the user's turn and inherit the user's provenance for it — the
laundering of §1's first clause, performed in the other direction. Provenance
describes where a span came from; it is not a label a component may apply to
material it assembled.

### 4. The conduit holds where the user's own act chose the recipient — and at `tools/` it does not

> **Normative.** Where the recipient is one the user's own act in that exchange
> selected, a user-authored span is disclosed by the user, and its transmission is
> not a disclosure this system made on the user's behalf. Sending the user's
> message to a model provider the user has explicitly configured (ADR-0004 §2, as
> amended 2026-07-19) is such a transmission, and a credential the user pasted
> into it does not make the call non-compliant.

> **Normative.** User-authored provenance is **not transitive** across a recipient
> the user's own act did not select. At the `tools/` seam the recipient is
> selected per call, so a user-authored span forwarded there is disclosed by this
> system in respect of that recipient, and its transmission needs the recipient
> authorisation ADR-0017 §3 already conditions the seam on.

**Provenance answers who discloses the *content*; authorisation answers who chose
the *recipient*. The conduit argument is the conjunction of the two, and it is
sound only where both halves hold.**

At `models/` both hold, and they hold structurally rather than by luck:

- The recipient set is fixed by **configuration**, not by the content. ADR-0004
  §2 as amended admits "only model providers the user has explicitly configured",
  and ADR-0013 §6's constraints keep fallback from widening it — "fallback is not
  permission to reach a provider the user never chose".
- The user's act of sending the message **is** the act of selecting that
  recipient. A person typing into an assistant they configured against a provider
  knows, at the moment of typing, the class of party that receives it.

At `tools/` neither half survives intact, and ADR-0017 §3 says so in its own
conditions before this ADR arrives. The destination is "the semantic recipient the
arguments select" — chosen per call, from arguments, which §3 already insists must
be canonicalised, authorised as one set, and bound to what was approved. A user who
types *book me a table* has not selected a restaurant's booking API as a recipient
of anything they typed; a model chose it, and by §1 the model's argument is a span
this system selected.

**So the answer to #94's second open question is: the conduit argument does not
reach the `tools/` boundary, and user-authored provenance does not authorise a
tool transmission.** What provenance settles there is *whose words these are* —
which is what a payload description and an approver need in order to be truthful
(§5) — and nothing about *who may receive them*. The recipient half stays exactly
where ADR-0017 §3 put it.

**Two things this deliberately does not do.** It does not forbid forwarding a
user's words to a third party: that is most of what an integration is for, and
forbidding it would be designing the seam in the ADR that is only meant to
classify its payload. And it does not decide which *form* of authorisation
suffices — §8 leaves the standing-policy question open by name, because ADR-0017
§3's condition already admits "a user decision **or a standing user policy**" and
narrowing that clause is not this ADR's to do.

**Why relativity to the recipient rather than a flat rule.** A flat "user-authored
content may always be sent" makes the system a laundry: anything the user ever
typed becomes freely disclosable to anyone the model names. A flat "user-authored
content is the system's disclosure" makes every model call a minimisation
violation, which is the false-on-day-one rule this ADR exists to avoid. The
relative rule is the only one of the three that is true at both boundaries, and
the asymmetry it produces is the asymmetry ADR-0017 §4 already chose deliberately:
"`tools/` is held to a stricter standard than `models/` on every axis… A boundary
that has never transmitted can be held to the standard we would want everywhere,
without prohibiting calls the product already makes."

### 5. The pasted credential is classified, not exempted: a user-authored free-text span asserts no tier

> **Normative.** A payload description or an audit record states **no tier** for a
> user-authored free-text span. It states the span's provenance and its extent,
> and it does not report the span as Tier 1.

> **Normative.** No gate, policy or approval treats a user-authored free-text span
> as having cleared a tier check.

**This is the direct answer to the failure ADR-0017 §3 names**, and it answers it
by removing the claim the failure runs on rather than by exempting anything. The
attack in §3's own words is: "an implementation could classify a pasted OAuth
token as Tier 1 because it arrived in conversation, **pass inspection**, and
disclose a credential under weaker policy." Each step is now blocked, and the
middle one is the load-bearing block:

- It cannot be **reclassified**: §1's first clause says a paste moves no tier, so
  a credential in the span is Tier 0 and stays Tier 0.
- It cannot be reported as **Tier 1**: the span's tier is *not determined* — the
  system genuinely does not know what is in it — and asserting Tier 1 would be
  asserting a fact nobody established. The honest description is *the user's own
  words, verbatim, N characters, to <destination>*.
- It therefore cannot **pass inspection**, because it never acquires a tier claim
  to pass inspection with. A policy keyed on tier has nothing to key on, and the
  second clause says so explicitly rather than leaving it to be inferred from the
  absence.

**"Classified, not exempted" is exactly what this is, and the distinction is worth
being precise about.** The span *is* classified: it is a user-authored free-text
span of stated extent, and that classification carries obligations — it is not
tier-cleared, it is not transitive across a recipient (§4), and it is not a route
for system-held Tier 0 (§3). What it is not is *tiered*, and a description that
invented a tier for it would be the exemption wearing a classification's clothes.

**The decision that remains is the user's, taken against a truthful description.**
Only the user can tell whether their own paste contained a key. §3's "named
approver able to refuse" is the surface where that is decidable, and a description
saying *your words, to this recipient* puts the question where it can be answered.
That is containment, not prevention, and §7 says so in those words.

**A structured argument field is a different case, and this clause does not reach
it.** Where an implementation places a value into a named argument whose meaning
it knows — a recipient address, an account identifier, a credential reference —
the tier is determined by ADR-0004 §1 as usual and is described as usual. The
no-tier rule is about **free text**, which is the case where the system holds no
knowledge of the contents. Saying otherwise would let an implementation escape
tiering by wrapping a known value in prose.

### 6. What must be recorded so an audit can tell the two apart

> **Normative.** The lane that designates the `tools/` seam records each span's
> discloser provenance with the payload it binds before transmission, and carries
> it into the audit record, so that a later reader can tell user-disclosed content
> from system-selected content in a transmitted payload without re-reading the
> content.

> **Normative.** That obligation binds no boundary that transmits today, and
> `models/` acquires no precondition from this ADR.

**The requirement is stated; the mechanism is not, and the split is deliberate.**
Whether provenance rides on a `core` type, on a wrapper the seam constructs, or on
the payload description itself is a contract decision, and ADR-0073 §4 sets the
standing test for one of this shape — decided "**with a producer in hand**", not
guessed. Nothing at the `tools/` seam transmits, so no producer exists whose
demands would shape the field, and ADR-0094 §10 and ADR-0098 §5 each declined the
same surface on the same ground. §8 defers it with its trigger.

**"Without re-reading the content" is the operative half.** The alternative — an
auditor deciding provenance by reading the payload back — would require the audit
store to hold the content, and ADR-0017 §3 already refuses that direction for the
same reason on a neighbouring value: credential *values* are excluded from the
authorisation binding, or "the binding and every audit record derived from it
become Tier 0 stores". A provenance an auditor must reconstruct from the text is
also the inference §2 forbids, arriving late.

**The second clause is the honest scoping and it is not an oversight.** `models/`
transmits today with no per-call payload description, no per-call approver and no
per-call recipient decision — its recipient set is configuration. Requiring it to
carry span provenance would be requiring a description that does not exist, which
is a precondition on the one boundary ADR-0017 §2 forbids adding preconditions to.
The classification of §§1–4 still holds at `models/`; what does not bind there is
the *recording*. ADR-0017 §4's asymmetry argument is the precedent, and it is
better to say this than to write an obligation `main` silently fails.

### 7. What this posture does not detect, stated so that nothing claims it

> **Normative.** No ADR, lane or surface states or implies that this posture
> detects a credential inside a span whose recorded classification is not Tier 0.

> **Normative.** No clause of this ADR is satisfied, and no bound in this corpus
> is obtained, by a detector of apparent secrets (#75). Such a detector is
> best-effort and is never a gate.

**The residual, named exactly.** A credential the user pasted is Tier 0 by
ADR-0004 §1 and this system cannot see that it is. Three consequences follow and
all three are accepted:

- It travels to the configured model provider inside the user's own message, and
  §4's first clause says that call is compliant. The user disclosed it.
- Once it is stored in an episode, §2's third clause makes it **system-selected**
  in every later exchange — and it will be re-selected as ordinary Tier 1
  conversation history, because that is its recorded classification. §3's first
  clause is not breached, because §3 is keyed on what a component *holds as*
  Tier 0; it is also not helping. This is the gap, stated rather than papered
  over.
- Nothing in §5 makes the payload description wrong, because the description
  asserts no tier for the span. It says *the user's words*, which is true.

**Why the gap is not bought back with a filter.** ADR-0098 §6 rules that "No
detector of injected instructions is a gate" and, more sharply, that no ADR "may
state a bound it obtains from such a detector" — because "the failure mode is not
adding a filter; it is a later ADR reasoning 'the filter catches that' and
therefore relaxing a ceiling". A secret-paste detector has the identical shape:
base64 blobs, hashes and code the user wants explained are false positives with a
real cost, and a determined paste is a false negative. #75 may ship as a
user-facing warning and is welcome as defence in depth; it may not appear in
anyone's argument that a clause here is satisfied.

**What does bound the undetected case, honestly enumerated.** The value reaches
only providers the user explicitly configured (ADR-0004 §2 as amended, ADR-0013
§6). It is never disclosed to a third party without §4's second clause routing
that through ADR-0017 §3's recipient authorisation, where a per-call approver sees
the destination. It is subject to the user's own delete right (ADR-0004 §6) and to
the offline destruction ADR-0126 provides. And the user, who is the only party who
knows the paste happened, is the one shown the description. That is a real
containment and it is not a prevention; the distance between those two words is
this ADR's accepted cost, and naming it is preferable to a rule that looks like it
closed the gap.

### 8. What is not decided here

> **Normative.** No lane reads this ADR as adding a condition to ADR-0017 §3's
> list, as relaxing one, or as attesting that any of them is satisfied.

> **Normative.** Whether a standing user policy (ADR-0017 §3) or a standing grant
> (ADR-0021 §6) may authorise forwarding user-authored content to a third-party
> recipient is **not settled here**, and no lane infers an answer to it from §4.

> **Normative.** No lane cites this ADR toward designating the `tools/` seam
> beyond the one condition it settles, toward ADR-0124's boundary, or as
> authorising any transmission.

**It designates nothing and authorises no byte.** ADR-0017 §2 reserves designation
to a later ADR that "names the seam module, attests each condition is satisfied
and how, and records the transition". This ADR supplies the *content* of one
condition; whether that condition is thereby satisfied is the designating ADR's to
attest, and it is not attested here.

**It adds no `core` surface, and defers one seam with its trigger.** The marker
that carries a span's discloser provenance to an egress boundary is deferred, on
the three grounds ADR-0098 §5 enumerated for the analogous field: it is contract
surface and so is its own PR (golden rule 5, ADR-0015 §5); where it lands decides
its blast radius; and ADR-0073 §4's standing test is unmet with no producer in
hand. **Trigger: the lane that designates the `tools/` seam**, which is the first
lane with a producer, a payload description and an approver, and therefore the
first with evidence about the shape the field wants.

**It leaves ADR-0004 §7's minimisation rule as scoped**, exactly as ADR-0017 §9
did — "written about the model provider and stays as scoped". §10 argues why §7
does not become narrower by this ADR's existence.

**It decides nothing about detection (#75), nothing about residency (#95), and
nothing about the reader-side adversary model (#641's remainder).**

### 9. What the implementing lanes owe

No lane is owed by this ADR alone; each obligation rides with the lane that would
otherwise breach a clause. **The test below is marked and the rest of this section
is not**, because §11 puts this ADR in ADR-0089's marked regime, where a rule
stated only in a list item obliges nobody.

> **Normative.** A lane that implements §5 for a payload description ships a test
> asserting that a user-authored free-text span carrying a well-formed credential
> is described with its provenance and **no tier**, and that no gate in the path
> treats it as tier-cleared. A test asserting only that the span is present does
> not satisfy this clause.

- **The lane that designates the `tools/` seam** owes §6 in full, owes §4's second
  clause its enforcement point in the per-call authorisation, and owes the choice
  between a caller-stamped and a producer-declared provenance marker an argument
  against ADR-0094 §5's rule that a producer may not declare its own standing.
- **The prompt-assembly lane** (ADR-0072 §6's, ADR-0098 §9's, filed as **#672**)
  inherits nothing new here: §6's second clause exempts `models/` from the
  recording obligation, and ADR-0098 §2's marking is about *externality*, which is
  a different axis. It should record that the two axes are separate so a later
  reader does not collapse them.
- **Whoever revises a payload description or an audit projection** owes §5's
  no-tier rule for free-text spans and §6's provenance field, on the division
  ADR-0098 §7's third clause drew: the debt sits with the ADR that owns the
  projection, never with the surface reading it.
- **#75's lane**, if it lands, owes §7's second clause in its own text: whatever
  it ships is a warning to the user and satisfies no clause of this ADR.

### 10. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement in the later ADR's text, and it is made here.
Its test is whether a reader holding only the earlier ADR "would now act
differently, or read one of its clauses more widely than it now holds". Where the
answer is no, "no record is owed against it at all, on `Status` or in a note" and
the change "is recorded in the ADR that makes it, **and nowhere else**".

**ADR-0004 §1 — no record owed.** Its sentence assigns a tier to a stored value.
This ADR assigns no tier, reclassifies nothing, and adds no fourth tier; §1's
first clause above *restates* §1's own axis rather than narrowing it. A reader
holding only ADR-0004 §1 acts identically before and after. Extending §1 to
express a discloser axis, by contrast, would have been a decision change requiring
a superseding ADR (ADR-0070 §1) — which is the second half of why this ADR stands
alone rather than landing as an amendment to it.

**ADR-0004 §5 — no record owed.** The redaction net stays keyed on field names and
keeps every property it claims. This ADR neither widens it nor relies on it; §7
says plainly that nothing detects a credential in a body, which is what §5 already
implies rather than a correction to it.

**ADR-0004 §7 — no record owed, and this is the one that needs the argument.** §7
reads: "collect and store only what a capability needs, and send the minimum
necessary **context** to the model provider." A reader might fear that §4's first
clause narrows it by exempting the user's own message. It does not, because §7's
sentence never reached that message: "context" is this architecture's own term for
what `context/` assembles — `CLAUDE.md`'s pipeline lists "context assembly" as a
stage distinct from the request that enters it — and a minimisation rule read as
obliging the system to trim the user's own question would forbid answering it.
ADR-0017 §9 already read §7 this way, scoping it to the model provider and
declining to read a tool-payload obligation into it. §7 therefore stands exactly
as wide as it was.

**ADR-0017 §3's classification condition — no record owed.** The condition is not
made false or over-wide by being answered; it stands as written and stays a
condition. What changes is a fact in the world, and ADR-0017 §2 reserves the
attestation that the condition is met to the designating ADR, which this is not.
A lane holding only ADR-0017 still finds §3's thirteenth entry and still follows
it to #94, which is where this ADR is filed.

**ADR-0017 §9 — no record owed.** Its sentence records what ADR-0017 declined to
decide and that #94 is a §3 condition. Both remain true as history, which is the
form ADR-0017 §6 chose for the prior amendment's declining clause: "a record of
what that amendment did and deliberately declined to do".

**ADR-0098 — no record owed, and the compatibility is stated rather than
asserted.** §1's external/not-external axis and this ADR's user-authored/
system-selected axis are independent, and the Context above works the four
combinations. Nothing in ADR-0098 becomes false or over-wide: its class is defined
on inbound origin, ruled on recorded origin, and this ADR adopts the same
discipline on a different question. Where they meet — a user's paste — the two
agree, ADR-0098 §1 holding it is not external and §1 here holding it is
user-authored.

**No ADR is amended and none is superseded**, so no `Status` line and no appended
note is written anywhere in `docs/adr/` but this file. Under ADR-0082 §1 a
reviewer "may not demand a record, or its removal, on book-keeping grounds alone",
and may require one by "naming the sentence of the earlier ADR that does, or does
not, become false or over-wide" — which is the form a disagreement with this
section takes.

### 11. Marking, review and ratification

This ADR is in **ADR-0089's marked regime**: it carries well-formed clauses, so
the marked clauses are the whole of what it obligates and the prose beside them
supplies nothing. ADR-0089 §5 makes marking forward-only, so nothing this ADR
cites is retro-marked and the unmarked ADRs it reads bind as prose exactly as
before.

It is **drafted, reviewed and revised while `Proposed`**, and its status is
flipped only once **both** required reviews — adversarial and architecture, the
set the header bullet declares — have returned clean on one tree, with both
re-run on the flipped tree for coverage. `CONTRIBUTING.md` → "Finishing an ADR
PR" owns that sequence and ADR-0130 §12 and ADR-0136 §7 are the worked
precedents; this section names the route and does not re-argue it. The ratifying
edit records the outcome (ADR-0070 §1).

## Consequences

- **ADR-0017 §3's outbound-payload-classification condition has an answer**, so
  the designating lane inherits a settled classification rather than negotiating
  one mid-implementation. Thirteen conditions remain, the seam stays undesignated,
  and `tools/` still transmits nothing.
- **The rule is true on the day it is written**, at all three of ADR-0124 §1's
  boundaries, which is the property #94 says the naive version lacks. It is
  checkable, because every clause is keyed on what a component recorded or holds,
  never on what a span contains.
- **A per-span provenance marker becomes owed** at the `tools/` seam, and it is
  `core` surface — so the designating lane either carries an ADR for it or stacks
  behind one. §8 names the trigger; nobody may implement against the seam before
  that contract merges (golden rule 5).
- **Payload descriptions get harder to write and more honest.** A description can
  no longer summarise a call as "Tier 1 data to X"; it must say whose words each
  span is, and it must decline to tier the user's free text. That is more work for
  the seam and a better question for the approver.
- **The pasted-credential gap is now written down with its bound**, rather than
  being an unstated assumption. If #75 ships, it does so as a warning and changes
  none of the clauses here; if it does not, nothing in this ADR was relying on it.
- **A later ADR wanting to let a standing grant cover third-party forwarding has a
  clean question to answer**, left open by name in §8 rather than pre-empted — the
  shape ADR-0098 §3 used for the same class of question.
- **Revisit trigger.** The first designated tool egress. If the seam's payload
  description cannot express "provenance, extent, no tier" without a `core` field,
  that field's ADR is the moment to re-read §§5–6 against a real producer.
