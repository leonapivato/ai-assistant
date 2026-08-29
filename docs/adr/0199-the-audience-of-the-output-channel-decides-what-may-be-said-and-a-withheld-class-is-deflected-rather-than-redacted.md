# 199. The audience of the output channel decides what may be said, and a withheld class is deflected rather than redacted

- Status: Partially superseded by ADR-0203 (§5's second clause, only as it reaches an operation whose output channel's audience is unbounded) and ADR-0204 (§3's third clause, only as it reaches a record whose provenance records that content §3 withholds from a channel of unbounded audience stood in its warrant) and ADR-0210 (§5's third clause, only as it reaches an operation whose output channel's audience is unbounded — the composing stage is told where the withholding removed something standing in the members of the turn's supply a relevance read taken with the turn's own goal statement returned, or a context facet, and not where the only thing removed stood in the conversation's own recent turns)
- Date: 2026-08-27
- **Partially superseded: 2026-08-28 by ADR-0203 — §5's second clause, only as it
  reaches an operation whose output channel's audience is unbounded, and nothing
  else of §5 or of this ADR.** The milestone-19 QA run (#1691) drove this ADR's
  ruling end to end on a live hub and filed #1692 and #1693. §5's second clause
  opens "The withholding subtracts from what the turn produced and adds nothing.
  The `TurnResult` the turn produced is unchanged", and an implementation reading
  it applies the subtraction to the composing stage's supply alone. Planning has
  already run over everything by then, so the plan rationale is authored by a
  model that saw the withheld records; ADR-0074 §3 captures that rationale into an
  episode whose own recorded origin is `OBSERVED` with `about_person` unstated,
  which §3 above places **speakable**; and the next spoken turn retrieves it and
  reads it aloud. The same rationale and the same records travel on the
  operation's return value, which is #1693.

  **Replaced — the turn's own supply, on such an operation, and nothing else.**
  ADR-0203 §1 subtracts what §3 withholds **before the turn plans**, so the turn
  is produced over the subtracted supply and no stage of it — planner, composing
  stage, or anything rendering what either produced — ever sees a withheld record.
  A reader now acts differently, which is ADR-0070 §1's test, so this is a
  supersession rather than an amendment, and it is **partial** in ADR-0070 §3's
  sense.

  **Not replaced — the rest of that clause, which is the load-bearing half.** The
  composing stage still gains no `ContextProvider`, no `MemoryStore`, no second
  context assembly and no second retrieval, and its context and its memories still
  reach it from the turn and from nowhere else (ADR-0170 §2). ADR-0203 §2 restates
  all four prohibitions and adds that nothing is refetched to replace what the
  subtraction removed. The narrowed copy an implementation makes for the stage
  today does not move — it ceases to exist.

  **Not replaced — anything else in this ADR.** §1's audience test, §2's
  recorded-origin discipline, §3's placements in both directions, §4's asymmetry,
  §5's first clause and its third through ninth, §6, §7, §8 and §9 all bind
  exactly as they did. In particular §5's first clause — withheld **at supply**,
  never a filter over composed prose — is not merely preserved but extended: the
  supply site moves one stage earlier and the ruling stays on the input side.
  ADR-0203 places no class and unplaces none.
- **Partially superseded: 2026-08-28 by ADR-0204 — §3's third clause, only as it
  reaches a record whose provenance records that content §3 withholds from a
  channel of unbounded audience stood in its warrant, and nothing else of §3 or of
  this ADR.** ADR-0204 §1 gives that record two routes and no third: the supply the
  turn producing it ran over held such content, or it was derived from a record
  whose own field is set. §3's third clause places as speakable "a belief
  whose `Provenance.source` is `USER_ASSERTED`, `OBSERVED` or `INFERRED` and whose
  `about_person` is not stated", and a captured episode is that by construction
  (ADR-0074 §4). The milestone-19 QA run and its re-drive filed **#1703** and
  **#1708**: an episode captured by a turn whose supply held withheld content is
  placed speakable by that clause and is supplied to a later turn on a channel of
  unbounded audience — on the typed channel carrying the categories of the withheld
  beliefs in its plan rationale, and on the spoken one carrying the owner's own
  question back.

  **Replaced — the placement of a stamped record, and nothing else.** ADR-0204 §1
  adds `Provenance.supplied_withheld_content`, §2 sets it from the supply the
  producing turn ran over, and §3 withholds a stamped record from a supply site for
  a channel of unbounded audience whatever this clause would otherwise place it as.
  A reader holding only this ADR supplies that record and now withholds it, which
  is ADR-0070 §1's test, so this is a supersession and it is **partial** in
  ADR-0070 §3's sense.

  **Not replaced — every other record §3 places.** No class becomes speakable or
  unspeakable, none is unplaced, and a record carrying no stamp is placed by §3's
  third clause exactly as it was. §3's first clause (the Tier 0 floor), second
  clause (the withheld classes), fourth and fifth (the notification key), sixth
  (what an admitting ADR owes), seventh and eighth all bind unchanged.

  **Not replaced — §2, and this is the clause a reader will check.** §2's first
  clause enumerates the recorded origin from which *§3's placements* are computed,
  and ADR-0204 computes none of them differently; it adds a separate reason to
  withhold, decided from a separate recorded field. §2's second clause — never by
  inspecting the words — is obeyed exactly, and ADR-0204 §1's argument is that a
  predicate over recorded origin is the *only* content-free form the marking could
  take. §2's third clause is untouched.

  **Not replaced — §5, §1, §4, §6, §7, §8 and §9.** §5's first clause puts the
  withholding at supply, which is where ADR-0204 §3 puts this one, and §5's third
  through ninth clauses shape a deflection that is unchanged. §1's audience test,
  §4's asymmetry, §6's user act, §7's household deferral, §8's gate and §9's
  deferrals are all as they were.
- **Partially superseded: 2026-08-29 by ADR-0210 — §5's third clause, only as it
  reaches an operation whose output channel's audience is unbounded, and nothing
  else of §5 or of this ADR.** The milestone-20 QA run (#1765) drove this ADR,
  ADR-0203 and ADR-0204 end to end on a live hub and filed **#1775**. §5's third
  clause fires "Where content was withheld", over the whole of the turn's supply —
  and ADR-0074 §5 puts the conversation's own recent turns in that supply because
  they are *the conversation* rather than because they answered the question. So
  once ADR-0204 stamped one spoken turn's episode, the next turn's tail held that
  episode, ADR-0204 §3 withheld it, and the stage was told a withholding had
  occurred on every later turn whatever was asked. #1775 records the owner-visible
  result: the time of day answered with *"There's something else related to that I'd
  rather not say out loud"*, and a spoken channel with no history to read back.

  **Replaced — the clause's condition, and only on that channel.** ADR-0210 §1 tells
  the composing stage where the withholding removed something standing in the
  members of the turn's supply that a relevance read taken with the turn's own goal
  statement returned — ADR-0074 §5's second and third groups, named by the read and
  not by the group, because ADR-0158 §4's deduplication drops from the supplement a
  record the tail already holds — **or a context facet**. It is not told where the
  only thing removed stood in the conversation's own recent turns. A reader holding
  only this ADR tells the stage whenever anything was withheld from the supply;
  after ADR-0210, on one channel, they do not, which is ADR-0070 §1's line.

  **Not replaced — what a deflection is and what it must contain.** The obligation
  §5's third clause imposes on the answer is untouched: where the stage *is* told,
  the answer still states the withholding, still carries no span of and no value
  derived from what was withheld, and still names a bounded channel where one can be
  named. Only the condition is narrowed. §5's first, second and fourth through ninth
  clauses are untouched, so the withholding is still at supply and never a filter
  over composed prose, and a turn on which nothing speakable remains still says so.

  **Not replaced — §3, §2, and everything else.** §3's placements are computed
  exactly as they are and no class becomes speakable or unspeakable; §3's sixth
  clause, which puts the posture of a newly admitted facet on the admitting ADR, is
  obeyed rather than moved — ADR-0210 §1 keeps facets in the evaluation for that
  reason, so a facet arriving unplaced is loud rather than quiet. §2's
  recorded-origin discipline binds whole: nothing ADR-0210 decides reads
  `MemoryBase.content`, a facet's rendered text, a goal statement, a plan or a
  composed reply, and nothing there asks a model what a passage is about. §1's
  audience test, §4's asymmetry, §6's user act, §7's household deferral, §8's gate
  and §9's deferrals are all as they were.

## Context

### Every surface built so far has had one reader, and a loudspeaker is the first that does not

The CLI writes to a terminal somebody is sitting at. The gateway renders a page
into a browser it admitted. In both, the person who receives the answer is the
person who asked for it, and the question "who hears this?" has never had to be
asked because the transport answered it.

A spoken channel breaks that in the **output** direction, and only there.
`track:voice` milestone 19 (#1318) is push-to-talk in the browser: an explicit
press on an authenticated web session, hub-side speech-to-text, the composed
reply, spoken back. The request path is untouched — the press is the principal,
exactly as a typed message is. What changes is that the answer is emitted into a
room, and everyone in the room receives it whether or not the system has any idea
they are there.

#665 is the issue that names this, and its framing is the one this ADR takes:
*"Speaker ID gates who the hub thinks asked; nothing gates who hears the answer."*
It asks for five things — a disclosure tier for spoken output, whether presence
evidence may tighten it, the shape of the answer given when full read-back is
refused, whether the user can grant "may be spoken" per class, and what happens in
a household — and it asks for them ratified **before the first spoke that speaks**.
#1318's opening ruling makes this the track's first lane on that ground.

### What the corpus actually says about output, read rather than remembered

Six texts bear on this, and between them they leave a hole rather than a
disagreement.

**A reply is not gated by anything.** ADR-0170 §1 rules that composing a reply is
not a tool invocation and that "no reply is gated by ADR-0021 §5's floor, by
ADR-0148's per-call machinery, or by any clause of ADR-0017 §3, on the ground that
it is a reply". §1 puts a terminal composing stage after execution; §3 gives
`TurnOutcome` a `reply` field to carry what it composed. That is correct and this
ADR does not disturb it — a reply is the product, not an egress. But it means the
answer path has no disclosure rule of any kind on it, and ADR-0170 §2's clause
that the stage consumes "no `ContextProvider` and no `MemoryStore`" fixes its
inputs as the turn's own: `goal`, `context`, `memories`, `plan`, `memory_degraded`
and the `StepOutcome`.

**The one disclosure floor the corpus has is about tools.** ADR-0021 §5 rules that
a definition with a non-empty `discloses` "may not receive `ALLOW` with
`authorised_by` unset", over `DataTier`, and that *auto*-granted is the operative
word. It is a rule about a **tool sending bytes off the device**, and ADR-0170 §1
puts a reply outside it deliberately. So the floor is not weakened by a speaking
channel; it is simply not engaged by one.

**The tiers exist and are already `core`.** ADR-0004 §1 classifies stored data as
Tier 0 (secrets), Tier 1 (personal data) and Tier 2 (operational), and
`core/types.py` carries them as `DataTier`. §3 puts Tier 0 in the OS keyring and
nowhere else; §5 forbids Tier 0 or Tier 1 in a log. Nothing in ADR-0004 says
anything about what may be *uttered*, which is the gap #665 opened it against.

**The band ceiling is about submissions, and its surface is deferred.** ADR-0094
§5 rules that the hub decides the band of what a spoke submits and that every
spoke has a ceiling a submission may not exceed. That is the **input** direction,
and #1318's design note 1 proposes extending the same move to output audience. It
is a good direction and this ADR takes it — but §5's own closing paragraph is
explicit that "where the ceiling is declared, and what a spoke's identity is, are
deliberately not decided", and §10 defers "an enrolment record, a capability
descriptor, a band-ceiling field, a spoke identity" together, firing when a second
spoke exists. **There is therefore no ratified surface today on which a channel
declares anything about its audience**, and an ADR that assumed one would be
writing against a document that does not exist.

**A grant is about reading, and says so in terms.** ADR-0097 §1 keys a grant on "a
reader's declared identity" and rules that it "authorises **reading that source
and proposing what it read**, and nothing else. It authorises no tool call, no
transmission…". §2 closes `GrantScope` at exactly two members, `FACET` and
`INGEST`, and §7 forbids a `SourceGrant` ever being cited as
`PermissionRuling.authorised_by`. ADR-0139 adds the surface that reads standing
grants from the store rather than from what the hub can offer. So the grant
machinery is real and live — and it is not, as it stands, a machinery for
authorising speech. What it supplies to this decision is a **form**, not a field.

**The escalation shape already exists.** ADR-0037 §4 rules that `CONFIRM` parks
the step and that "the turn never answers on the user's behalf"; ADR-0044,
ADR-0052 and ADR-0059 make the park durable and recoverable. That is the pattern
#665 asks the degraded answer to reuse: the turn stops, says what it needs, and
waits for the user on a surface that can carry the act.

### The session is not the channel, and milestone 19 is where that first bites

At milestone 19 there is exactly one authority in play. ADR-0168 §3 rules that "a
browser session carries the device's whole authority", and §4 that the session is
the gateway's own admission record — "not an enrolment, not a grant, not a
principal". Whether the answer is rendered as text or spoken by the same page, the
authority behind it is identical.

The **audience** is not. The rendered page reaches a person who is positioned at
the screen and looking at it; the loudspeaker reaches everyone within earshot,
with no act of theirs at all. One session, two channels, two audiences — which is
why an audience rule cannot be derived from an authority rule, and why the browser
tab is genuinely a third surface beside the shared room and the private ear
(#1318, design note 1).

There is a second reason the decision cannot be deferred to the surface that
speaks. ADR-0175 §4 rules that a delivery returned by a poll "is written to
**every** delivery stream open at the moment it returned, unchanged", and that the
gateway "filters nothing, de-duplicates nothing, **withholds nothing**". That is
the right rule and this ADR does not touch it — but it means a disclosure decision
taken at the gateway is a decision the gateway is forbidden to take. Whatever
governs a speaking channel has to bind **before** the content exists, at the point
where what the answer is made of is chosen.

### An honest statement of what this ADR is not allowed to settle

It decides conduct: what the composing stage may put into a reply bound for a
given channel. It adds no Protocol, no `core` type, no field and no setting, and
it may not — golden rule 5 puts a contract surface behind its own ratified ADR,
and ADR-0094 §10a marks that requirement for exactly this family of surfaces.

It does not decide the audio mechanism — capture, transport, engine selection or
playback — which belongs to the ADR deciding that mechanism, written in parallel
with this one and deliberately not cited by number here, because ADR-0088 §6's
Tier 1 check refuses a citation to a number nobody has issued. It does not decide
the spoke enrolment surface ADR-0094 §10 defers. It does not decide person identity, enrolment or
speaker identification, which ADR-0101 §3 filed as **#691** after finding that
those questions had been mis-filed against #665, an output-side question that
decides none of them.

## Decision

We will make the **audience of the output channel** the thing a disclosure posture
is a function of; decide a class's membership from recorded origin rather than
from the words; withhold three classes from a channel whose audience is unbounded,
with an unplaced class withheld by default; refuse ever to widen a posture on
sensed evidence; and require a withheld class to be **deflected at composition**
rather than redacted out of a composed answer.

### 1. The posture is a function of the output channel's audience, and never of the authority the request carried

> **Normative.** An **output channel** is a path by which a reply or a delivery
> reaches a person. Its **audience** is **bounded** when what the channel emits
> reaches a person only through an act of that person's own — being positioned at
> and looking at a rendered surface, or wearing the device that emits — and the
> system holds a fact tying that act to the session it admitted. Its audience is
> **unbounded** in every other case, and in particular whenever what the channel
> emits reaches whoever is within range of the device with no act of theirs.

> **Normative.** A channel whose audience is not declared has an **unbounded**
> audience for every purpose of this ADR. No implementation, lane or later ADR may
> read an absent declaration as bounded, as unknown-and-therefore-permitted, or as
> a case to decide at run time from anything other than a declaration.

> **Normative.** The disclosure posture of a reply or a delivery is a function of
> the audience of the channel it is bound for, and of nothing else. It is not a
> function of the modality, the transport, the device, the authority the request
> carried, the session that admitted the request, or the identity of whoever
> asked.

> **Normative.** One session may own channels of differing audience, and a posture
> decided for one of its channels does not reach another. No lane may derive a
> channel's audience from the admission record of the session that owns it.

**Audience rather than modality, because "voice" is not one trust level.** A room
speaker and a bone-conduction earpiece are both audio and are not the same
surface; a rendered page and a printed sheet left on a desk are both visual and are
not either. Design note 1 of #1318 states the frame — a spoke's properties price
it, so that "neither ADR needs special cases for devices that don't exist yet" —
and *output audience* is the one property this decision needs. Keying on the
property rather than on the device is what lets a worn earpiece be admitted later
without an amendment, and what stops a kitchen speaker being admitted early
because it happens to be running the same client.

**Undeclared reads as unbounded, and that is the clause that makes the rest
enforceable.** The alternative — an undeclared channel treated as bounded until
something says otherwise — puts the burden on the wrong party: a lane that adds a
speaker and forgets to say so gets the permissive answer, silently, and the
failure is exactly the one #665 was opened about. Fail-closed here costs a lane
one declaration.

**The session/channel split is stated because the tempting shortcut is to collapse
it.** ADR-0168 §3's clause that a browser session "carries the device's whole
authority" is about what the browser may *ask for*. A reader who carried that
across to disclosure would conclude that anything the page may render, the page
may also speak, because it is one admitted session either way. That inference is
the whole failure this ADR exists to prevent, and it is available in one step from
a ratified sentence, so it is refused in terms rather than left to be noticed.

### 2. A class is decided from recorded origin, never by inspecting the words

> **Normative.** The **class** of a piece of content is decided from what the
> system recorded about where the content came from, and never by inspecting the
> content for what it appears to be about. For a belief the recorded origin is
> `Provenance.source`, together with `Attestation.reported_by` where the band is
> `ATTESTED` (ADR-0092 §1), and `MemoryBase.about_person`. For a context facet it
> is the facet's own kind and its `source`. For a notification it is
> `NotificationCandidate.producer`, `NotificationCandidate.notification_class` and
> `NotificationCandidate.sensitivity`.

> **Normative.** No implementation, lane or later ADR may decide a class by
> reading `MemoryBase.content`, a facet's rendered text, a composed reply, or any
> other span of the content itself — not by keyword, not by pattern, not by a
> classifier, and not by asking a model what a passage is about.

> **Normative.** Content whose origin the supplying component did not record has
> no class, and content with no class is withheld from a channel whose audience is
> unbounded.

**This is ADR-0155 §3's discipline read in the output direction.** That section
rules that membership of covered content "[is] decided at each supply site from
recorded origin … and never by inspecting content for resemblance, which is the
unrecoverable relation ADR-0098 §5 and §12 forbid deciding on". The same argument
transfers without weakening: a rule that "health facts are not spoken" enforced by
looking for health words is a rule that fails on the first sentence that phrases a
diagnosis in ordinary language, and its failure is silent. Deciding on origin is
decidable, auditable, and wrong only in the direction that withholds.

**And the origin is already on the record, which is why no taxonomy is minted
here.** `Attestation.reported_by` is documented as "the connected source
*instance*", is required to be stable across syncs (ADR-0092 §3), and is the same
value ADR-0097 §1 keys a grant on — chosen there precisely "because the join to
the belief already exists". A spoken-disclosure rule keyed on the same value
inherits that join for free, and a lane that adds a source has one place to state
its posture rather than a second classification to maintain beside the first.

**A notification is classifiable on the same terms, and the fields are already
there.** `NotificationCandidate.producer` is documented as "the producer's declared
name — a stable Tier 2 name, on ADR-0093 §7's rule for a reader's identity", which
is the same rule `Attestation.reported_by` is chosen under;
`notification_class` is "declared by the producer and not a configurable value";
and `sensitivity` is a `DataTier` "never defaulted", with `DataTier.SECRET`
"refused at validation (ADR-0130 §2)". So the delivery path is not a hole this rule
cannot reach — it is a second supply site with its own three recorded values, and
ADR-0130 §2's refusal of `SECRET` at construction is §3's Tier 0 floor already
enforced there by the type. The candidate also "references and does not contain"
the records it is about, so classifying it does not reach through to the beliefs it
names.

**A class with no recorded origin is a real case and not a hypothetical.** A
component that composes a value out of several inputs and records nothing about
them has produced content this rule cannot place, and the third clause says what
happens to it rather than leaving a hole for an implementer to fill permissively.
It is the same shape ADR-0021 §5 gives an `UNKNOWN` cost — "an absence of
information", never auto-granted — and ADR-0016 §4's fail-closed reading of the
same word.

### 3. Three classes are withheld from an unbounded channel, and an unplaced class is withheld

> **Normative.** No reply and no delivery, on a channel of any audience, carries a
> Tier 0 value or any span of one (ADR-0004 §1). This is a floor rather than a
> posture: no user act, no configuration, no grant and no later ADR short of one
> superseding this clause admits one to an output channel.

> **Normative.** Content withheld from a channel whose audience is **unbounded**
> is: any record whose `MemoryBase.about_person` is stated; any content of a class
> the owner has recorded as unspeakable under §6; and any content of a class no
> ratified ADR has placed as speakable on such a channel.

> **Normative.** These classes are placed as **speakable** on a channel of
> unbounded audience: a belief whose `Provenance.source` is `USER_ASSERTED`,
> `OBSERVED` or `INFERRED` and whose `about_person` is not stated; a belief whose
> band is `ATTESTED` and whose `Attestation.reported_by` names the calendar source
> ADR-0093 §7 configures, again where `about_person` is not stated; and a
> `CalendarFacet` or an `EmailFacet`, each of which carries no span of any entry or
> message by its own ratified construction.

> **Normative.** No notification is placed as speakable on a channel of unbounded
> audience by this ADR. An ADR admitting a delivery channel of unbounded audience
> places what it places on the whole of §2's recorded origin for a notification —
> `NotificationCandidate.producer`, `notification_class` **and** `sensitivity` — and
> what it does not place stays withheld.

> **Normative.** A candidate matching a placement in `producer` and
> `notification_class` while carrying a `sensitivity` that placement does not name
> is withheld. No implementation reads a placement as reaching a tier it did not
> name, and no placement names `DataTier.SECRET`.

> **Normative.** An ADR admitting a new source, a new facet, a new notification
> producer, or any other producer of content that can reach an output channel
> states the posture of what it produces on a channel of unbounded audience, in its
> own text. It may not settle that question by silence, and until it does, what
> that producer produces is withheld from such a channel.

> **Normative.** Content whose class is placed as speakable is not thereby
> authorised for any channel this ADR says nothing about, and a placement is a
> permission about audience alone.

> **Normative.** Nothing in this ADR authorises egress. ADR-0017 §1 and §3,
> ADR-0154 §2 and ADR-0155 §1 and §3 are untouched, and no lane cites this ADR
> toward a designation, a registration or a destination.

**The Tier 0 floor is stated even though nothing puts a credential in a reply
today.** #665 asks for it, ADR-0004 §3 keeps Tier 0 in the keyring and §5 keeps it
out of logs, and ADR-0170's composing stage is supplied nothing that holds one —
so the clause forbids a case that is currently unreachable. It is worth a line
anyway: it is the one rule in this ADR that is not a posture and is not
overridable, and stating it as a floor is what keeps §6's user act from ever being
read as reaching it.

**`about_person` is the household clause, and it is decidable today.** ADR-0100
puts the subject axis on `MemoryBase` and documents it precisely: the field is
"whom this belief is about, when that is someone other than the owner", stated or
`None`, with `None` "read as the owner's" and the owner never named. So "is this
belief about somebody else?" is a field read, on ratified surface, with no
inference in it. And the person a belief is about is, in a household, exactly the
person most likely to be in the room when it would be read aloud — which makes
this the highest-value withholding available and the cheapest to enforce. It also
sits squarely inside ADR-0099 §1's second clause, that the store "records what
this assistant holds on the owner's behalf, and never purports to record what is
true of another person independently of the owner": a belief the owner holds about
their partner, uttered into a room the partner is standing in, is that framing
failing in the only way a user would ever see it.

**The speakable set is named rather than left as "everything not withheld", and
the difference is the whole safety property.** A permissive default would mean
that the next source to land — a health integration, a message reader, a
photograph — is speakable on the day it merges, by omission, and that #665's
answer decays with every lane that does not think about it. Naming the set inverts
that: an unplaced class is withheld, the fourth clause tells the admitting ADR what
it owes, and the cost of forgetting is an answer that deflects rather than an
answer that discloses.

**The set is also large enough that milestone 19 works, which is the test the
naming has to pass.** #1318's exit for milestone 19 is the owner asking aloud about
their own life and hearing an answer drawing on accumulated memory. That answer is
made of the owner's own beliefs and the calendar, and every one of those is placed
speakable above. A rule that passed the safety test and failed the exit test would
be a rule nobody could ship.

**The two facets are placed by reading what they actually carry.** `CalendarFacet`
is three scalars and an instant and documents that "it carries no entry text — no
summary, location, description, organiser, attendee or identifier". `EmailFacet` is
two scalars with "no span of any message — no sender, address, display name,
subject, body, identifier or per-message instant", and its own docstring gives the
reason: a subject line is "attacker-chosen text on the advisory path". So #665's
worked example — "calendar yes, email no" — turns out to have no purchase on the
facets, because neither discloses anything an utterance could leak. Where the email
question really lives is in the beliefs a message reader would propose, and those
are unplaced by the second and fourth clauses until the ADR admitting that reader
places them. Recording that the example moved is better than honouring it in the
place it was aimed at.

**`sensitivity` is in the placement key because dropping it would widen a
placement by construction.** The field is "the producer's chosen sensitivity, never
defaulted", chosen per candidate rather than per class, so one producer's one class
can emit an `OPERATIONAL` candidate and a `PERSONAL` one — "your build finished" and
"your build failed on the branch you pushed from the clinic" are the same producer
and the same class. A two-field placement would admit both on the strength of the
narrower one, which is the unintentionally broader class this ADR exists to refuse.
The key therefore ranges over exactly two tiers rather than three: ADR-0130 §2
refuses `DataTier.SECRET` at validation, so §3's Tier 0 floor is already enforced on
this path by the type, and the last clause states the consequence rather than
relying on the type to keep holding it.

**Health sits at the bottom, and this is where that is said.** Design note 2 of
#1318 records that health data is "the most sensitive tier we would ingest", that
its "retention and disclosure [are] stated at the moment the first grant is
designed", and that health facts "sit near the bottom of any spoken-disclosure tier
even though they are the most tempting thing to surface proactively". No health
source exists, so there is nothing here to place — and the fourth clause is exactly
the instrument that carries the note's obligation to the lane that lands one,
without this ADR pretending to legislate over a producer nobody has built.

### 4. Sensed evidence tightens and never widens, and no voiceprint makes anything speakable

> **Normative.** Evidence about who is present — occupancy, presence, diarization,
> speaker identification, a paired device in range, or any other sensed signal —
> may move a channel's audience from bounded to unbounded, and may never move it
> from unbounded to bounded.

> **Normative.** No sensed signal, and no match against any voiceprint or other
> biometric, makes any content speakable that would otherwise be withheld, admits
> a class §3 withholds, or raises what an output channel may carry.

> **Normative.** No lane, implementation or later ADR cites this ADR toward voice
> as a credential, or toward any rule by which what a channel may carry rises on
> evidence about who is present.

> **Normative.** Where occupancy is unknown, the posture is the one that applies
> when the channel's audience is unbounded. Unknown occupancy is never an
> exception, a degraded case, or a reason to consult a default other than the
> tighter one.

**The asymmetry is design note 1's, and its ground is a property of the signal
rather than a preference.** A voiceprint is identification, not authentication:
clonable from a few seconds of audio, unrevocable, and matched over an open-air
microphone that is a shared injectable medium. Evidence with those properties can
support a claim that *more* people may be present — because it costs nothing to
be wrong in that direction — and cannot support a claim that *fewer* are, because
being wrong there is the disclosure itself. #665 states the constraint the same
way: "a 'sounds like the owner, so read it aloud' rule is authorization by
voiceprint with extra steps".

**The second clause is a refusal, so it is marked.** ADR-0089 §1 rules that "a
refusal is normative" where it forbids something a later lane could otherwise do,
and this is the one a later lane will most want: a room that sounds empty is
enormously tempting as a licence, and the temptation arrives with a plausible
mechanism attached. Refusing it in terms is what turns a later attempt into a
visible supersession argument rather than an accretion of reasonable-looking
widenings — ADR-0101 §3's phrasing for the same hazard.

**Unknown occupancy is the common case, not the edge case, and milestone 20 is
where that becomes obvious.** #1318's milestone 20 is an unprompted utterance into
a room nobody addressed; there, nothing has told the system anything about who is
present, and a rule whose default was permissive would be permissive almost always.
Stating the default as the tighter posture is what makes the milestone-20 behaviour
fall out of the rule rather than needing a special case written for it later.

### 5. A withheld class is deflected, not redacted, and the deflection is composed rather than filtered

> **Normative.** Content withheld from a channel under §3 is withheld **at
> supply**: it does not reach the composing stage among the inputs from which the
> reply bound for that channel is composed. No implementation composes a reply and
> then removes, masks, blanks or rewrites part of it to satisfy this ADR.

> **Normative.** The withholding subtracts from what the turn produced and adds
> nothing. The `TurnResult` the turn produced is unchanged; the composing stage
> gains no `ContextProvider`, no `MemoryStore`, no second context assembly and no
> second retrieval; and its context and its memories still reach it from the turn
> and from nowhere else (ADR-0170 §2). No lane satisfies this ADR by having the
> stage fetch, re-assemble or re-retrieve anything.

> **Normative.** Where content was withheld, the composing stage is told **that** a
> withholding occurred, and composes an answer that states it. Where a channel of
> bounded audience can be named on which the answer can be had, the answer names
> one; where none can be named, it names none and says nothing further about what
> was withheld.

> **Normative.** A deflection carries no span of the withheld content and no value
> derived from it — not a paraphrase, a summary, a count over it, a category, a
> subject label, or any other value that narrows what was withheld. It is composed
> from what was speakable on that channel, plus the fact of the withholding and the
> channel it names.

> **Normative.** Where the turn was addressed to the assistant and nothing
> speakable remains, the answer states that it cannot be given on this channel and
> carries nothing else. No implementation substitutes a partial answer, an apology
> carrying the subject, or a reply that makes the withheld content inferable beyond
> the bare fact that something was withheld.

> **Normative.** Where nothing was addressed to the assistant — a delivery, or any
> other emission on a channel nobody asked on — and §3 withholds the whole of what
> would be emitted, the outcome on that channel is **silence**. Nothing is emitted
> announcing that something was withheld.

> **Normative.** A delivery whose content §3 withholds from a channel of unbounded
> audience is **not emitted on that channel**, and no deflection is spoken in its
> place. Delivery on a channel of bounded audience is unaffected.

> **Normative.** Such a notification is neither discarded nor retired on that
> account: it stays in the hub's durable outbox (ADR-0131 §3) and is delivered on a
> channel that can carry it **if and when a device asks on one**. This ADR promises
> no delivery in the absence of such a channel and creates no channel; ADR-0131 §1
> keeps delivery an answer to a request a device made, and ADR-0130's own retention
> and expiry govern the entry unchanged, so a notification may expire unread.

> **Normative.** A reply composed for a channel of bounded audience is never
> emitted on a channel of unbounded audience. A component that fans one value out
> to several channels either emits only on channels whose audience the value was
> composed for, or emits nothing.

**Withholding at supply rather than redacting at output, for two reasons that
point the same way.** The first is §2's: a filter over composed prose is content
inspection, which §2 forbids as a decision procedure, and which fails silently on
the first sentence phrased in a way the filter did not anticipate. The second is
ADR-0094 §5's, on the input path, and it transfers whole: an over-ceiling
submission is "refused, not downgraded and not silently reclassified", because
silent reclassification "produces a record that is *plausible* and wrong". A
composed answer with a hole cut in it is exactly that — an utterance the listener
cannot distinguish from a complete one.

**The deflection is ADR-0037 §4's escalation shape, reused rather than reinvented.**
That section rules that `CONFIRM` parks the step and that "the turn never answers
on the user's behalf". The parked confirmation and the deflected answer are the
same move: the turn declines to complete on this surface, says what it needs, and
points at a place where the act can be taken. #665 asks for the pattern by name and
this is what it is; ADR-0044, ADR-0052 and ADR-0059 are the durable machinery
behind it, and none of them is engaged by this ADR, because a deflection parks
nothing and resolves nothing.

**Naming a channel is conditional, because the case where there is none is
ordinary rather than exotic.** A room speaker with no browser open and no other
enrolled device is the state a household kitchen is in most of the day, and a rule
that required naming a bounded channel there would have no satisfying output at
all. So the naming is conditional and the *stating* is not: the answer still says
that something was withheld, which is what keeps the remaining content from
reading as the whole of it.

**An addressed turn always answers; an unaddressed emission stays silent.** The two
clauses look like one rule with an exception and are two rules with different
subjects. When the owner asks a question aloud, silence is indistinguishable from a
system that failed, and #1318's milestone 19 exit test turns on a deflection being
*heard*. When nothing was addressed to the assistant — milestone 20's unprompted
utterance into a room — an emission whose entire content is "there is something I
will not say" is pure signal about the existence of withheld content, delivered to
a room that did not ask, with no answer to compensate it. The outbox is the right
place for that notification, and saying nothing is the channel declining rather
than the delivery path failing.

**"Details on your phone" is the shape and the third clause is what keeps it from
becoming a leak.** "You have a message from the clinic" is a deflection that
discloses the thing it declines to read. So is "there are two things I can't say
about Alice". The rule is that a deflection is composed from what was speakable
plus the bare fact — which is what makes "details on your phone" the model
sentence rather than a slogan.

**The delivery clause is what makes the rule implementable on the path that has no
composing stage.** A notification is not composed by ADR-0170's stage: ADR-0131 §1
rules that a delivery is "the result payload of a request that device sent" and
ADR-0130 decides the artifact long before any device asks. So "withhold at supply"
has no supply site there, and without the clause above a spoken delivery channel
would face three bad options — speak an unplaced class, inspect and redact contrary
to §2 and §5, or drop the notification silently. The clause takes the fourth: the
channel declines, and the outbox ADR-0131 §3 built for a notification nobody was
listening for holds it. Retiring it instead would be the delivery path losing a
notification to a disclosure rule, which is the one outcome ADR-0131 §3's durability
exists to prevent. What the clause deliberately does **not** promise is that the
notification arrives: the hub cannot open a channel — ADR-0131 §1 rules that
delivery answers "a request that device sent" — so an owner with nothing but a
speaker gets a pending entry, and ADR-0130's retention may expire it first. Stating
that is better than a guarantee this ADR has no instrument to keep.

**The fan-out clause is where the reply path and the delivery path meet, and it is
directed at the lane that adds speech.** ADR-0175 §4 rules that a delivery is
written to "every delivery stream open at the moment it returned, unchanged", and
that the gateway "filters nothing … withholds nothing". That clause is correct and
this ADR leaves it exactly as it stands: the gateway is a relay, and ADR-0175's own
reasoning is that keeping or re-judging what the hub gave it would be the authoring
golden rule 3 forbids. What follows for a speaking channel is not that the gateway
must start filtering — it is that a channel of unbounded audience may not be fed by
an undifferentiated fan-out at all. The obligation lands on whoever adds the speech,
and the clause above is stated over any component that fans out rather than over
the gateway, so that it binds the case wherever it next appears.

### 6. A "may be spoken" record is a recorded user act, and it is not a `SourceGrant`

> **Normative.** No `SourceGrant` (ADR-0097) authorises speech. No implementation
> or later ADR reads a grant, a `GrantScope` member, or a standing grant returned
> by `AssistantEngine.standing_grants` (ADR-0139 §2) as permission to put anything
> on an output channel.

> **Normative.** No lane adds a `GrantScope` member expressing this ADR's posture
> without an ADR deciding that surface, merged before anything implements against
> it (golden rule 5).

> **Normative.** The owner may record that a class §3 placed as speakable is
> withheld, and that a class §3 withheld under its second or third limb is
> speakable, on channels of unbounded audience.

> **Normative.** No such record reaches §3's Tier 0 floor or a record whose
> `about_person` is stated. Both stay withheld under every record the owner makes,
> and no surface offers either as something the owner may admit.

> **Normative.** A record under the clause above is created **only** by an explicit
> user act through a client. No model, plan, tool, reader, scheduler job, `Settings`
> value, migration, upgrade or first run creates one, and no installation infers one
> from a source it is already reading or a channel it is already serving.

> **Normative.** The store holding such records is append-only, and a withdrawal
> is a further record rather than a mutation of the one it withdraws.

> **Normative.** A posture is read from that store, and never from which sources
> the hub holds, which channels it is serving, or what a `Settings` value says.

> **Normative.** The surface carrying these records — its Protocol, its types, its
> operations and its client rendering — is not decided here, and no lane implements
> one without an ADR deciding it (golden rule 5).

**#665 asked whether this shares #629's open decision space, and the answer
changed while the issue was parked.** The owner's own note on #665 records the
change: "the grant machinery landed (ADR-0097/ADR-0139), so the ADR can build on it
rather than defer to it". That is right, and the way it is right is narrower than
it looks — **what landed is a form, not a field.**

**A source grant cannot carry this, and ADR-0097 says so in three places rather
than one.** §1: a grant "authorises reading that source and proposing what it read,
and nothing else. It authorises no tool call, no transmission …". §2: `GrantScope`
has exactly two members, and both gate a *read*. §7: a `SourceGrant` "may never be
cited as `PermissionRuling.authorised_by`", stated there against precisely this
failure — "a calendar-read grant silently authorising an off-device transmission —
the floor satisfied by a consent the user gave about something else entirely". A
"may be spoken" permission read off a grant is that sentence with the word
"transmission" changed. So the first clause above is ADR-0097 §7's rule applied to
a second subject, and it is stated because the shortcut is one step away from a
ratified record and would look, from inside, like reuse.

**What is inherited is ADR-0097's shape, clause for clause.** A recorded explicit
user act through a client (§1), never minted from configuration or an upgrade (§8),
append-only with revocation as a record (§4), read from the store rather than from
what the hub can offer (ADR-0139 §2). Those four properties are what make a grant
mean anything, they are independent of what a grant is *about*, and adopting them
here costs nothing and settles the design questions the surface lane would
otherwise re-argue.

**The asymmetry in the second clause is deliberate and matches ADR-0101 §1's.** The
owner may tighten anything and may loosen only within bounds — the Tier 0 floor and
another person's data are outside what a single owner act may reach, the second
because ADR-0099 §1 makes the store the owner's model of a world containing other
people, not those people's own record. ADR-0101 §1 draws the same line for the same
reason: "a destructive store operation is never given an optional scope whose absent
or default value widens what it destroys. A read may be."

### 7. Multi-person household disclosure: what is decided, and what is deferred

> **Normative.** §3's withholding of a record whose `about_person` is stated binds
> whoever asked and whatever the system believes about who is present. It is the
> whole of what this ADR decides about a household, and no lane reads it as
> deciding more.

> **Normative.** Whether a household member other than the owner may ask anything
> at all, and what they may be told, is **not** decided here, and no lane builds a
> second principal, an account, a subject-scoped permission system or a second
> identity in one hub's store on the strength of this ADR. ADR-0099 §1 and §3 are
> untouched.

**The deferral has a condition and a holder, which is what ADR-0094 §10 requires of
one.** It fires when person identity exists — **#691**, the issue ADR-0101 §3 filed
after finding that ADR-0099 §5 and ADR-0100 §6 and §12 had filed person identity
against #665, "an output-side disclosure question whose own text treats the request
path as settled elsewhere". Until a person can be named, "the matched speaker asking
about another member's data" has no subject to be about, so there is nothing here to
decide well. #665 and #1318 both name it and both defer it, and this ADR does the
same rather than inventing a registry ADR-0101 §3 spent its §3 keeping out.

**What is not deferred is worth saying plainly, because the deferral would
otherwise read as covering it.** The decided half is real and it is the half that
protects the third party: the beliefs the owner holds about other people are not
read into a room today, under any grant, on any evidence about who is present. That
costs the owner the ability to ask aloud about their partner's birthday, and the
compensation is §5's deflection to the screen — which is the trade #665 proposes and
the one this ADR takes.

### 8. Conduct, not protocol: what an ADR deciding the spoken channel owes, and the gate on shipping

> **Normative.** This ADR adds no Protocol and no member to one, no `core` type
> and no field on one, no setting, no method signature and no tool. Every rule
> above is a rule about conduct at the composing stage and at whatever emits what
> it composed, and a lane needing any of those needs its own change and, where
> golden rule 5 reaches it, its own ADR.

> **Normative.** No lane ships an output channel whose audience is unbounded until
> a ratified ADR has decided the surface by which a channel's audience reaches the
> composing stage. The rules above are unenforceable without it, and an unenforceable
> disclosure rule is the state #665 was opened to end.

> **Normative.** An ADR deciding that surface states how a channel declares its
> audience, and gives a channel that declares none the unbounded reading of §1. It
> may not make the audience a value a spoke asserts per request, and it may not let
> a channel raise its own audience from unbounded to bounded — the output-side reading
> of ADR-0094 §5's rule that "a submission never raises its own".

> **Normative.** An ADR deciding the mechanism of a spoken channel is the consumer
> of §5's deflection shape, and states in its own text how a deflection reaches the
> user on the channel it names. It decides nothing this ADR decides, and this ADR
> decides nothing about capture, transport, engine selection or playback.

**The gate is the load-bearing clause of this section, and it is the one #665 asked
for.** The issue's own terms are that the decision be "ratified before the first
spoke that speaks"; this ADR is that ratification, and the second clause is what
keeps it from being a document a lane can ship past. It costs milestone 19 nothing
it was not already paying: ADR-0094 §10 defers the spoke surface with the firing
condition "when a **second** spoke exists", the gateway is that second spoke
(ADR-0168 §1), and #1318's milestone 21 already records that "the surface should
predate this milestone". What this clause adds is that the *audience* half of it
predates the first loudspeaker, which is earlier.

**The third clause is ADR-0094 §5 read in the other direction, and the reading is
the reason it is safe to extend.** §5's rule is that "a spoke may not decide, claim,
or influence the band of what it submits, and a claim carried in a submission is not
evidence of the standing it claims". The output-side analogue is exact: a channel
that could assert "I am private" is a channel that can talk its way into content, and
the assertion is unverifiable at the hub in precisely the way §5's is. Note what is
*not* being extended — §5 itself is untouched, its subject is still submissions, and
§10's deferral of where a ceiling is declared is honoured rather than pre-empted.

### 9. Deferred, by name, each with the condition that fires it

- **The surface on which a channel's audience is declared.** Fires with the ADR
  deciding the spoke surface ADR-0094 §10 defers, or earlier with the first channel
  of unbounded audience — §8's second clause makes the earlier one binding.
- **The surface carrying a "may be spoken" record** (§6). Fires with the first
  posture the owner wants that differs from §3's placement. Until then §3's
  placement is the whole of the posture, which is a workable steady state and not a
  good one — the same shape ADR-0021 §6 records for standing grants.
- **Multi-person household disclosure** (§7). Fires with person identity, **#691**.
- **Arbitration across several channels hearing one utterance** — #1318's design
  note 3. It is an input-path question (one utterance, one execution) and this ADR
  is output-side; it fires with the second spoke that hears, at milestone 21.
- **The posture of any source that does not exist yet**, health foremost among
  them (#1318, design note 2). Fires with the ADR admitting that source, under §3's
  fourth clause, which is a deferral with an obligation attached rather than an open
  question.

### 10. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 requires the judgement in the later ADR's text, naming the clause and
applying ADR-0070 §1's test: would a reader holding only the earlier ADR now act
differently, or read one of its clauses more widely than it now holds?

**No record is owed on any earlier ADR. Every rule above is a stacked addition.**
The five clauses a reader would check:

- **ADR-0170 §1's "no reply is gated … on the ground that it is a reply".** That
  clause is about ADR-0021 §5's floor, ADR-0148's machinery and ADR-0017 §3, and it
  is used here as given: this ADR engages none of the three, adds no permission
  check to the reply path, and gates nothing.
- **ADR-0170 §2's "Its context and its memories are the ones the turn already
  assembled".** This is the clause a reader would reach for, and the test is applied
  to it rather than asserted past. Read with the prose ADR-0089 §3 makes available
  for exactly that purpose, the clause fixes the **provenance** of the stage's
  inputs and not their cardinality: its own heading is "The stage consumes **no
  `ContextProvider` and no `MemoryStore`**", its closing sentence is "It performs no
  second context assembly and no second retrieval", and its rationale is about the
  composition root and about not reaching through `Engine`'s collaborators for a
  provider. **The decisive test is that an implementation satisfying §5 still
  satisfies every clause of ADR-0170 §2**: the stage holds no provider and no store,
  assembles nothing a second time, retrieves nothing a second time, and receives
  what it receives from the turn and from nowhere else. §5's second clause states
  that in terms so the compatibility is a rule rather than a reading. What changes
  is that a subset is supplied where a superset was available — an addition of an
  obligation, contradicting no sentence ADR-0170 wrote, which is ADR-0082 §1's
  stacked addition rather than ADR-0070 §1's supersession. Declaring it a
  supersession would be the mis-declaration ADR-0082 §1 warns of, and would edit a
  `Status` line on a decision this ADR leaves entirely intact.
- **ADR-0130 §2 and ADR-0131 §1 and §3.** §2's recorded-origin list for a
  notification reads three fields ADR-0130 put on the candidate, for a purpose it did
  not name and does not exclude; §5's delivery clause declines a channel and leaves
  the outbox's durability doing exactly the job ADR-0131 §3 built it for. Neither
  ADR gains or loses a sentence, and a reader holding only them builds the same
  producer, the same artifact and the same outbox.
- **ADR-0175 §4's "filters nothing … withholds nothing".** Untouched, and §5's
  reasoning says why: the obligation is stated over a component that fans out to
  channels of differing audience, which the gateway of ADR-0175 is not — every
  delivery stream there is a browser stream. A reader holding only ADR-0175 builds
  the same gateway.
- **ADR-0097 §1, §2 and §7.** §6's first clause restates §7's prohibition against a
  second subject; it widens nothing and narrows nothing, and a reader holding only
  ADR-0097 already may not cite a grant for a transmission.
- **ADR-0094 §5 and §10.** §8's third clause states an obligation on a *later* ADR
  and changes no sentence of either. §5's subject stays submissions; §10's deferral
  of where a ceiling is declared stays deferred and is honoured by §8's second
  clause rather than discharged by it.
- **ADR-0004 §1, §3 and §5, ADR-0099 §1 and §3, ADR-0100, ADR-0101.** Each is read
  and applied. §3's Tier 0 floor forbids a case none of them addressed; §3's
  `about_person` clause reads a field ADR-0100 defined, for a purpose ADR-0100 did
  not name and does not exclude; §7 leaves ADR-0099 §1 and §3 exactly as written.

**This ADR marks its rulings** (ADR-0089 §5), so the marked clauses above are the
whole of what it obligates and the prose beside them is read to determine what a
marked clause means.

**Status.** Drafted, reviewed and revised while `Proposed`. The required set for
this change is **adversarial alone**: it touches neither `core/protocols.py` nor
`core/types.py` and decides no contract surface — §8's first clause is the
statement of that — so `CONTRIBUTING.md` → "Stop when the required reviews are
green" puts it outside the contract-surface case. The status was flipped only once
that review returned clean on one tree, by the one-line flip ADR-0165 §2 exempts;
the sequence is `CONTRIBUTING.md` → "Finishing an ADR PR", and nothing implements
against this ADR until it merges (ADR-0015 §5, golden rule 5).

## Consequences

**Easier.** #665 closes on an answer to all five of the things it asked to be ruled
on, and milestone 19 acquires a disclosure rule it can be built against: the
composing stage filters its own inputs on two fields that already exist, and the
answer either comes back whole or comes back deflected. The rule is device-agnostic
in the way #1318's design note 1 wanted — a worn earpiece and a kitchen speaker are
priced by one property rather than by two special cases — so the wearable ladder
(design note 2) needs no amendment here to arrive. And a lane adding a source now
has one sentence to write and a stated default if it does not: withheld.

**Harder, and stated plainly.** The owner loses the ability to hear, out loud,
anything the store holds about another person, and loses it before the household
question is decided — so a rule aimed at a partner in the room also fires when the
owner is alone in the house. That is the cost of a posture that may not be widened
on sensed evidence (§4), it is deliberate, and §6's user act does not relieve it.
The compensation is the deflection, and the deflection is only as good as the
bounded channel it can name.

Every new producer of content now carries a disclosure obligation into its own ADR
(§3's fourth clause), which is a real tax on lanes that would rather not think about
voice. The alternative is worse in the specific way §3 describes: the set decays
silently, one merged lane at a time.

And an unbounded channel cannot be shipped until a surface exists to declare an
audience (§8), which puts a contract lane ahead of milestone 19's speech. That is
the sequencing #665 asked for — "ratified before the first spoke that speaks" —
rather than a new obstacle, but it is a lane that has to be dispatched and it is not
this one.

**Revisit if** a channel appears whose audience is genuinely dynamic within a
session — the composite-spoke routing #1318's design note 2 describes, where
"private output is only true while audio actually routes to the earpiece" — since
§1's audience is written as a property a channel declares and that case declares one
that changes underneath the reply; if person identity lands and §7's deferred half
becomes decidable; or if a producer arrives whose content has no recorded origin at
all and whose withholding under §2 turns out to be the common case rather than the
exception.

## Alternatives considered

**Key the posture on the session's authority rather than on the channel's
audience.** One rule, no new concept, and it follows in one step from ADR-0168 §3's
"a browser session carries the device's whole authority". Rejected because it is the
error: at milestone 19 one session owns both the screen and the speaker, so an
authority-keyed rule says the two may carry the same content, which is the exact
conclusion #665 exists to forbid. The failure is invisible in the tree — nothing
distinguishes the two channels — and irreversible in the room.

**Redact the composed answer.** Compose normally, then remove what may not be said.
Attractive because it needs no change to what the composing stage is supplied, and
it is what a reader assumes "disclosure filter" means. Rejected twice over: it can
only decide what to remove by inspecting the words, which §2 forbids for ADR-0155
§3's reason, and an answer with a hole in it is ADR-0094 §5's "plausible and wrong"
output — the listener cannot tell it from a complete one.

**Deny by default, with no named speakable set.** The maximally conservative shape:
nothing crosses an unbounded channel until an ADR admits its class. Rejected because
it fails milestone 19's exit test on the day it merges — the owner asks aloud about
their own life and hears a deflection — and a rule nobody can ship is not a
conservative rule, it is an absent one. §3's named set is the same discipline with
today's classes actually placed.

**Allow by default, withholding only a named list.** The mirror image, and the one
that reads as pragmatic. Rejected because the list is a snapshot: the first source
that lands after it is speakable by omission, silently, and the omission is invisible
at review because nothing in the new lane's diff mentions voice. §3's fourth clause
is the inversion that makes forgetting fail closed.

**Mint a `GrantScope` member — `SPEAK` beside `FACET` and `INGEST`.** The smallest
possible surface, on a store that already exists, with revocation and disclosure
already built. Rejected on ADR-0097's own terms: §1 confines a grant to reading a
source and proposing what it read, §2 grounds both members in ADR-0093 §3's two
reading consumers, and §7 forbids a grant authorising anything but a read. A third
member would be a use that is not a reading, on a key that is a reader's identity,
in a store whose value is that its records say what the user decided about reading.
§6 keeps the form and refuses the field.

**Let occupancy evidence widen the posture when the room is confidently empty.** The
single most requested behaviour this decision will face, and the one with the
clearest user story. Rejected in terms (§4): the evidence is a sensed signal over a
medium anyone in range can inject into, being wrong costs exactly the disclosure the
rule exists to prevent, and admitting it is voice-as-credential arrived at by a
different road. #665 names this constraint as inherited rather than new.

**Scope the whole decision to replies, and leave notification deliveries to
milestone 20.** Tempting because a delivery is not composed by ADR-0170's stage, so
§5's "withhold at supply" has no supply site on that path and the rule needs a
second disposition to be implementable. Rejected because the delivery path is where
#1318 says "the disclosure rules bite hardest" — an unprompted utterance into a room
nobody addressed — and a decision that governs the answer to a question and not the
interruption nobody asked for has ruled the easy half. The second disposition turns
out to be cheap: `NotificationCandidate` already carries `producer`,
`notification_class` and `sensitivity`, so the classification exists, and declining
the channel costs nothing because ADR-0131 §3's outbox is durable.

**Defer the whole decision to the ADR that builds the spoken channel.** One lane
instead of two, with the mechanism and its disclosure rule decided together by
whoever holds the context. Rejected because #665's own terms are that the rule be
ratified before the first spoke that speaks, #1318's opening ruling makes this the
track's first lane on exactly that ground, and a disclosure rule written by the lane
that wants to ship the feature is a rule with one thumb on the scale. The mechanism
ADR gets the deflection shape as a constraint (§8) rather than as a question.
