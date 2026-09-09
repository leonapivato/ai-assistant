# 242. The act that trusts a destination has its own surface, and a search that did not happen is explained in the reply

- Status: Proposed
- Date: 2026-09-09
- **Partially supersedes** [ADR-0231](0231-the-planner-asks-for-a-search-the-turns-own-words-compose-it-and-the-results-come-back-as-records.md)
  — **§9's third clause, and nothing else in that ADR.** That clause reads *"The composing
  stage is told nothing new, and the assembled prompt on a turn whose search was refused is
  byte-identical to what it would be had the planner asked for nothing"*. §7 below tells the
  composing stage one closed-vocabulary member on a turn whose search did not happen, so a
  reader holding only ADR-0231 would assert a byte-identity that no longer holds — ADR-0070
  §1's test met, and §3's partial form is the sanctioned tool. **§9's first, second, fourth
  and fifth clauses bind entire**: a `WEB_SEARCH` request is still serviced only on a
  recorded `ALLOW`; the servicer still asks the user nothing and parks nothing; no lane
  makes a search reachable by weakening its declaration; and the one route to an `ALLOW` is
  still ADR-0193's standing recipient grant. §13's audit, §19's deferrals and every other
  section stand entire, and the `SearchDisposition` enumeration ADR-0241 §8 leaves closed at
  eighteen is not widened here.
- **Partially supersedes** [ADR-0235](0235-the-establishing-act-rides-an-answer-to-a-confirmation-live-or-recorded-and-a-refused-search-reaches-the-user-as-history-and-not-as-work.md)
  — **§8's first clause, and nothing else in that ADR.** That clause reads *"The message
  that a search was refused is `grantable_decisions`' listing and the act offered beside it,
  on the surfaces §9 admits, and is **nowhere else** … No lane puts the message in a reply,
  appends it to one, degrades one for it, or reads ADR-0228 §10's carrier as covering it"*.
  §7 and §9 below put a statement of what did not happen in the reply and a statement of the
  act beside it. **§8's second clause binds entire** — this is not a notification, and no
  lane mints one for a search that did not happen — **and §8's third clause binds entire**:
  the listing still states what the recorded decisions say and no more, and neither the
  reply nor the line beside it states that the turn would have answered differently, that a
  reply was incomplete, that a search would have succeeded, or that anything is owed. §§1–7
  and §§9–14 are untouched, and §9's browser deferral and voice withholding are inherited
  rather than moved.
- **Partially supersedes** [ADR-0228](0228-a-serviced-read-may-revise-the-plan-once-and-the-turn-stops-looking-at-a-bound-or-a-deadline.md)
  — **§10's first clause, in its second sentence alone.** That sentence reads *"On every
  other turn it is given nothing, and the assembled prompt is byte-identical to what it is
  today"*, and it is false of a turn §7 below's carrier covers. **The first sentence binds
  entire** — a turn that stopped at the bound or the budget with a `read_request` still
  standing is still given that fact and still composes an answer that says so — and §10's
  remaining four clauses bind entire and are the pattern §7 follows rather than the thing it
  moves: the carrier still travels inside `ai_assistant.orchestration` as data, is still
  never inferred at the render site, and still reaches no step account. §§1–9 and §§11–15
  are untouched.
- **Partially supersedes** [ADR-0238](0238-a-destination-the-user-chose-may-be-told-what-the-turn-knows-and-the-searching-that-follows-runs-under-a-per-conversation-budget.md)
  — **§1's `record` refusal clause, in the type of the refusal alone.** That clause has
  `record` refuse *"a duplicate `id`, an empty destination set and a record duplicating a
  live record's destination set, by an `InvalidDestinationTrustError` beside
  `InvalidRecipientGrantError`"*; §2 below gives the third ground a subclass,
  `DuplicateDestinationTrustError`, because it is the one ground on which the user's recourse
  is *no act at all*. A reader holding only ADR-0238 would build one class for three grounds,
  so ADR-0070 §1's test is met. **The base class keeps every ground** and a caller wanting
  one handler still writes one `except InvalidDestinationTrustError`; the refusal is moved in
  its type and in nothing else. **Everything else in §1 stands entire** — the two-member
  vocabulary, the fail-closed absence, the set-by-a-user-act-and-nothing-else clause, the
  record's five fields, the canonical-destination validator, the `UNCHOSEN` construction
  refusal, the five-member store surface with its no-member-added clause, `record`'s
  atomicity, `export`'s data right, and `trust_of`'s comparison-not-inference rule — as do
  §§2–18. In particular **§14's assignment of the surface is discharged rather than
  superseded**, and the Context section below argues why.

## Context

### Where this comes from

Milestone 31's closure requires **#2168**, adopted from the owner's 2026-09-09 amendment on
#1908: *"Reachable setup for destination trust and recipient authorisation, plus
explanations of refused or exhausted searches."* Its acceptance is stated as a journey:
*"From the supported user surface, establish the required authority, perform contextual
follow-up searching, and demonstrate the missing-authority, revoked-authority, and
exhausted-allowance cases."* And it fixes the route: *"Any new boundary-crossing type or
Protocol requires its own ratified ADR."* This is that ADR for the first half of #2168; the
recipient-authorisation half already has one, and it is ADR-0235.

The requirement has two halves and they fail differently. **Setup** fails by being
unreachable: ADR-0238 designed the fact and the store and then, deliberately, shipped no way
for a user to set it. **Explanation** fails by being forbidden: two ratified clauses say in
terms that a turn whose search was refused composes a reply byte-identical to one where
nothing was asked. The first half is a gap; the second is a decision that the owner's
amendment reverses. This ADR does both, because they are one user journey and a surface that
offered the act without saying when it is needed would be a control nobody finds.

### The tree, read rather than assumed, at `origin/main` `2c8aebfc`

- **`AssistantEngine` carries fifty-four members** (`core/protocols.py`), of which five are
  ADR-0235's contiguous recipient-grant block: `grantable_decisions`,
  `establish_recipient_grant`, `standing_recipient_grants`, `recent_recipient_grants`,
  `revoke_recipient_grant`. **Nothing on the Protocol reads, writes or names destination
  trust**, and `DestinationTrustStore` is not in `core/protocols.py` at all — ADR-0238 is
  Accepted with nothing of it in the tree, and lane B1 of batch #2178 lands the triad.
- **`PROTOCOL_VERSION` is `31`** (`wire/envelope.py`), whose top log entry reads "31 since
  ADR-0235 §10" and records three simultaneous grounds. **ADR-0235 §10's own arithmetic —
  *"`PROTOCOL_VERSION` stands at **30** on `origin/main`"* — is a reading of an older tree**,
  exactly as that section says it is, and the rule it states rather than the number is what
  binds here.
- **Wire operations are not enumerated.** `wire/surface.py` derives them by reflection —
  `METHODS` is *"frozenset(name for name, member in vars(AssistantEngine).items() …)"* — and
  a result payload takes the shape of the method's own declared return annotation (ADR-0085
  §10). `wire/codec.py` holds no per-type registry and `wire/errors.py` derives an error code
  from `type(exc).__name__`. So an engine member **is** the wire operation, and the only
  hand-written wire cost is a `RemoteEngine` method in `wire/client.py`, the constant, and its
  log entry.
- **The command line carries ADR-0235 §9's four commands** — `remember-recipients`,
  `recipient-grants`, `recipient-grant-log`, `revoke-recipient-grant` — plus
  `--remember-recipients-until` on `resume`. `_drive_establish` reads the outcome **from the
  type of the exception** and `_render_recipient_grant_outcome` reads it **from the carrier on
  `TurnOutcome`**; neither parses a message and neither reads a store back. That pair is the
  precedent this ADR follows twice.
- **`SearchDisposition` has fifteen members in the tree** (`orchestration/reads.py`), values
  equal to their lower-cased names. **Three more are ratified and unlanded**: ADR-0238 §11's
  sixteenth, for a servicing `admit_search` refused, and ADR-0241 §§4 and 8's
  `DEADLINE_EXPIRED` and `SEARCH_FAILED`, which close that enumeration at **eighteen** — *"these
  two and no others"*. §8 below maps all eighteen. It lives in `orchestration` because it crosses no subsystem boundary, and the
  audit writes it as `servicings[].disposition` under the one event key `turn_read_request`.
- **One carrier reaches the composing stage today and it is a bare `bool`.**
  `Composer.compose` takes `stopped_while_asking: bool = False`, ADR-0228 §10's fact,
  threaded from `orchestration/loop.py` through `orchestration/engine.py`'s `_Composer`
  callable, rendered by a fixed prompt fragment `_STOPPED_ASKING_PROMPT` that instructs the
  model to say it stopped short and *"Do not say why you stopped, how long you had, how many
  times you looked, or what you would have looked for: you have not been told any of that."*
  Its sibling is `hop_reached: Sequence[str]` (ADR-0227 §3). **Nothing else tells the
  composing stage anything about a search**, and no reply the system composes today mentions
  one.
- **`assistant connect <identity>` mints a connection reference and authorises nothing** —
  its own help says so in terms — and `Settings.web_search_connection` and
  `web_search_origin` are the both-or-neither pair `app/composition.py` requires before a
  searcher is built at all.

### The assignment this ADR discharges, and why it is a fulfilment rather than a supersession

ADR-0193 §13 says: *"No lane reads this ADR as deciding **which** surfaces offer the
establishing act, what the wire carries for it, or how a browser or command-line surface lays
it out … The surfaces, and the revocation surface §9 assumes, are ADR-0177's, ADR-0178's and
ADR-0186's to decide."* ADR-0238 §14 restates it for its own act: *"The lane implements no
surface for §1's establishing act, and ADR-0193 §13's assignment binds unchanged … No lane
mints a trust record beside them."* ADR-0238 §16 then defers *"The surfaces that offer §1's
act"* with that assignment as the trigger.

**The assignment is a routing rule about who may decide, not a list of three files.** Read as
a list, it is already violated: ADR-0235 §9 fixed four command names and a `resume` flag for
the *recipient-grant* act, and ADR-0235 §11 records that it *"changes **one limb of one
clause** of ADR-0193 — §1's 'one class rather than several' … and nothing else in that ADR"*
— no supersession of §13 anywhere on the line. What ADR-0235 did instead was **record against
the governing ADR of each surface it reached**: it left ADR-0177 §1's browser enumeration
unwidened and said in terms that a browser surface *"is a **later consumer lane with its own
ratified decision**, which widens ADR-0177 §1's enumeration in its own text"*.

So §13's rule is discharged by an ADR that (a) decides the surface in its own ratified text
rather than leaving it to an implementing lane, and (b) records against the ADR that governs
each surface it touches. This ADR does both. It is the same discharge, on the second of the
two acts, by the ADR the batch commissioned for it.

### Claims in the framing that do not survive contact with the tree

**"Trust is recorded once at connection."** #1908's older wording says so and it is wrong.
ADR-0238 §1 is explicit that *"No configuration sets it, no connected account sets it, no
operator setting sets it"*, and `assistant connect`'s own text says a connection *"is not
permission to act, it authorises nothing"*. The ratified ADR wins and the surface must be an
act of its own.

**"The trust act can ride `grantable_decisions`' listing rows the way the grant act does."**
Half true, and the half that fails is the one that matters. ADR-0235 §3's fourth availability
condition is *"the trail holds no decision resolving it"*, so the instant a user performs the
grant act the row leaves that listing. A trust act keyed on the same availability set would
be unreachable for every user who granted first — which is the order the listing's own
next-step line teaches. §1 below keys the act on the recorded decision itself, with three
conditions and not seven.

**"An engine member and a wire operation are two things to decide."** They are one:
`wire/surface.py` derives the operation set from the Protocol by reflection. What is left to
decide is the member, not a second name for it.

**"A `SearchDisposition` member is enough to explain a refusal to the user."** It is not, and
this is the finding that shapes §8. `RULING_CONFIRM` is recorded both where **no grant covers
the recipients at all** and where **a grant stands but the request was planned over external
content and the closed loop is not closed** (ADR-0238 §5, §6; ADR-0193 §4). Those two have
different acts behind them — one is `remember-recipients`, the other is the trust act — and
the disposition cannot tell them apart. The servicing site can, because ADR-0238 §5 already
obliges it to read `trust_of` and the request's binding carries
`planned_with_external_content`. An explanation derived from the disposition alone would send
half of milestone 31's users to the wrong command.

### What this ADR is not allowed to settle

It decides no fact about a destination — ADR-0238 §1 owns the vocabulary, the record, the
store and the rule that a model never touches any of them. It decides no budget, no ceiling
and no monetary policy — ADR-0238 §8, §9 and §10 own those and #2116 stays where §9 put it.
It decides nothing about **how a search comes to be interrupted**: ADR-0241 (lane L1-ADR of
this batch, ratified and merged 2026-09-09) decides that a declared bound reaches
`WebSearcher.search`, that an expiry is its own `SearchDisposition` member, and how an
interrupted call is accounted; §10 below states the seam in terms and takes none of it. It adds no member to `DestinationTrustStore`, `AuditTrail`,
`RecipientGrantStore`, `ActionPolicy` or `EgressBinder`. It adds no `Settings` field. And it
does not decide what the *browser* does, which is ADR-0177's, deferred by name in §6 with the
trigger that fires it.

## Decision

### 1. The trust act rides a recorded decision, and it is a second question asked as a second question

> **Normative.** The act that records destination trust rides a **recorded
> `PermissionDecision`** and is offered on no other subject. The user names a decision from a
> listing that already renders the canonical destination set `core` derived, and the act
> records a `DestinationTrustRecord` over **that binding's canonical destination set,
> transcribed by value**. No surface accepts a destination the user typed, parses a host,
> builds a `CanonicalDestination`, or constructs a destination set of its own — which is
> ADR-0235 §4's *"It **accepts no `tool`, no `parameters_digest`, no `egress_binding`** …
> from its caller, so a caller has no parameter through which to substitute a subject"* read
> one act over, and ADR-0021 §3's move of removing the capability rather than forbidding it.

> **Normative.** The act is available on a decision meeting **all three** of the following,
> and is refused on any other: the trail holds a decision with that id; that decision's
> `egress_binding` is an `EgressBinding` — never `None`, never an `OriginUnrecordedBinding`,
> never a `CoverageUnrecordedBinding`; and that binding's `planned_with_external_content` is
> `False`. **Three and not ADR-0235 §3's seven**, and the four that are absent are absent for
> one reason stated below rather than by omission.

> **Normative.** The decision's **ruling**, whether the trail holds a decision **resolving**
> it, its `step_id` and `execution_id`, and its `expires_at` are **not** conditions of this
> act, and no lane adds them. ADR-0235 §3's four conditions over those fields exist because
> that act **seeks a ruling from `ActionPolicy.resolve` and records an answer**; this act
> seeks no ruling, records no answer, sends nothing, resumes nothing and services nothing, so
> there is no confirmation to answer once, no park to keep apart from history and no lifetime
> to be inside. A user may record trust from a decision they answered a month ago, and that
> is the point: it is what keeps the act reachable after the grant act has taken the row out
> of `grantable_decisions` (ADR-0235 §3's fourth condition).

> **Normative.** The third condition is the one this act keeps, and it is kept for a reason
> narrower and sharper than ADR-0235 §3's. Trust is precisely what closes ADR-0238 §5's loop
> and lets a later request be composed over what an earlier one returned, so **trusting a
> destination a model reached *from* external content is the loop closing on itself**: an
> injected page names a destination, the planner plans a call to it, the call is refused and
> recorded, and the recorded row is then offered to the user as something to trust. Refusing
> the act on `planned_with_external_content` cuts that at the only point where a rule can
> reach it, and it is refused **at this operation** rather than left to the store, because
> `DestinationTrustStore.record` does not consult a binding and could not (ADR-0238 §1's five
> fields carry no tool, no account and no call).

> **Normative.** Every refusal of the act raises **`UntrustableDestinationError`**, one new
> `AssistantError` subclass, and the operation writes nothing to any store on any of them. The
> message names which condition failed, **no lane branches on the message**, and where more
> than one fails the first in the order above is the one named, so the refusal is
> deterministic across implementations. It is an `AssistantError` and not a `ValueError` for
> `UngrantableActError`'s own stated reason: a `ValueError` escapes a command's `except
> (AssistantError, TransportError)` boundary as an uncaught traceback with no controlled exit
> code, which ADR-0042 §7 forbids.

> **Normative.** It is a **new class and not `UngrantableActError` reused**. That class's
> ratified meaning is ADR-0235 §3's ordered seven — *"the act was not performed, nothing was
> recorded, nothing was sent, and the call may still be answered without the standing
> request"* — and a caller catching it means *the recipient-grant act was unavailable*. Two
> acts with different recourses answering to one handler is what ADR-0235 §7's
> two-vocabulary rule refuses one noun over: *"One noun over two records that cannot
> substitute for each other is how a user comes to believe that revoking one revoked the
> other."*

> **Normative.** The two acts are **two acts, two commands and two records**, and no surface
> offers a single control, flag, prompt or keystroke that performs both. ADR-0238 §1's
> closing clause is what obliges it — *"A deployment reaching `USER_CHOSEN` has a user who
> answered the second question **knowing it was a second question**"* — and a flag on the
> granting command would make the second question a modifier of the first. What a surface
> **may** do, and §5 requires, is offer both acts **from the same listing**, name them as two,
> and never present either as completing the other.

> **Normative.** Trust **may** therefore be recorded from a `remember-recipients`-style
> listing of refused searches, and that is decided rather than left open: the listing is the
> only place in this system where a canonical destination set the user has a reason to
> consider is rendered whole beside the id that names it. What may not happen is the two facts
> collapsing into one record, one act or one answer. ADR-0238 §1's *"**The two acts are
> separate and neither implies the other**"* binds unchanged, and neither operation reads,
> consults or is influenced by the other's store.

### 2. The `core` surface: three engine members, two error classes, one enumeration, one field

> **Normative.** This ADR decides the following `core` surface and lands none of it. A
> contract that adds a member, widens an argument or changes a return is changing this
> decision rather than implementing it. The block is display, not a mark (ADR-0089 §2); the
> clauses around it are the obligations.

```python
class AssistantEngine(Protocol):                       # core/protocols.py
    async def establish_destination_trust(                      # §1
        self, decision_id: DurableIdentifier
    ) -> DestinationTrustRecord: ...

    async def standing_destination_trust(                       # §4
        self,
    ) -> tuple[DestinationTrustRecord, ...]: ...

    async def revoke_destination_trust(                         # §4
        self, record_id: DurableIdentifier
    ) -> bool: ...


class SearchNotServiced(StrEnum):                      # core/types.py, §7, §8
    SEARCH_DISABLED       = "search_disabled"
    NOT_ADMITTED          = "not_admitted"
    SPEND_EXHAUSTED       = "spend_exhausted"
    DECLINED              = "declined"
    TRUST_MISSING         = "trust_missing"
    AUTHORISATION_AWAITED = "authorisation_awaited"
    INTERRUPTED           = "interrupted"
    UNAVAILABLE           = "unavailable"


class TurnOutcome(BaseModel):                          # core/types.py, §9
    search_not_serviced: SearchNotServiced | None = None


class UntrustableDestinationError(AssistantError): ...  # core/errors.py, §1

# core/errors.py — the one ground on which the user's recourse is no act at all.
# The base still catches every refusal, so a caller wanting one handler keeps it.
class DuplicateDestinationTrustError(InvalidDestinationTrustError): ...   # §2
```

> **Normative.** Both identifier arguments are **`DurableIdentifier` and not `str`**, and
> `AssistantEngine`'s own second obligation is what fixes them: *"Every identifier argument
> undergoes `Identifier` validation before any I/O"*. `decision_id` names a
> `PermissionDecision.id` and `record_id` a `DestinationTrustRecord.id`, both of which are
> `DurableIdentifier` on the records themselves, so a client cannot make `" id "` and `"id"`
> disagree at the seam. The obligation is **inherited rather than restated**: this ADR adds no
> validation rule of its own and mints no error for a blank identifier.

> **Normative.** `establish_destination_trust` takes **no `trust` argument, no `destinations`
> argument, no `id` argument and no instant**. `trust` is `USER_CHOSEN` because ADR-0238 §1
> refuses a record asserting anything else at construction; `destinations` is transcribed from
> the decision's binding (§1); the record's `id` is minted by the engine and its
> `established_at` is the engine's clock read at the instant of the act, both *"as
> `RecipientGrant`'s is (ADR-0193 §1) … so that the record is a complete value before it
> reaches any store"* (ADR-0238 §1). There is no parameter through which a caller could
> substitute any of them.

> **Normative.** The record carries **no expiry**, and no surface offers one. ADR-0238 §1
> fixes the record at exactly five fields with `revoked_at` the only lifecycle member, so an
> `expires_at` would be a `core/types.py` change against that ADR's exact-shape clause rather
> than a flag a surface may add. **This is a real asymmetry with `RecipientGrant` and it is
> stated rather than smoothed over**: a recipient grant ends at an instant the user chose,
> and destination trust ends when the user revokes it. §14 defers an expiring trust record
> with its trigger.

> **Normative.** `DuplicateDestinationTrustError` is raised by `DestinationTrustStore.record`
> where a record duplicates a live record's destination set, and by that ground alone. The
> other two grounds ADR-0238 §1 gives `record` — a duplicate `id`, and an empty destination
> set — keep raising `InvalidDestinationTrustError` unchanged. The discriminator exists
> because the recourses differ and by ADR-0235 §4's argument verbatim: *"a user whose subject
> already stands needs **no** act at all, because what they asked for is already true"*, and
> reading the store and constructing a different record *"is what would give them a second
> authorisation they think is one"*.

> **Normative.** The outcome of the act is read from the **type of the refusal** and from
> nothing else. No lane parses a message, matches on its text, reads
> `standing_destination_trust` after a refusal to work out which ground it was, or infers the
> ground from a count it took itself. That is ADR-0235 §11's bar — *"not inferred from
> messages or a post-write read"* — read one store over, and it is why the subclass exists
> instead of a message convention.

> **Normative.** This ADR adds **no Protocol**, no member to `DestinationTrustStore`,
> `RecipientGrantStore`, `AuditTrail`, `ActionPolicy`, `EgressBinder` or `ConversationStore`,
> no `Settings` field, and no member to `RoutableOperation`. It adds **two** error classes and
> no third, **one** `core/types.py` enumeration, and **one** field on `TurnOutcome`. It adds
> no field to `DestinationTrustRecord`, `RecipientGrant`, `PermissionDecision`,
> `Confirmation`, `EgressBinding` or `Conversation`, and no second construction path for any
> of them.

> **Normative.** The engine holds the **`DestinationTrustStore` face** and no `interfaces/`
> adapter holds it, a `RecipientGrantStore`, a `RecipientGrants` or an `AuditTrail`. A surface
> is given records by the operations above and reads no store, which is golden rule 3 and
> ADR-0235 §4's clause read one store over: a renderer given the store face would hold
> `record`, `revoke` and `export`, and a remote client could not perform the read at all.
> `app/composition.py` stays the only place the concrete store is constructed (ADR-0238 §14).

> **Normative.** Every new operation is cancellable under `core/protocols.py`'s cancellation
> clause (ADR-0060), observes no caller-owned container (ADR-0065), and returns a **detached
> snapshot** — the tuple, the records in it, and everything mutable those reach (ADR-0018 §3),
> as every neighbouring promoted read does.

**Three members and not five, because two of ADR-0235's five have no question to answer
here.** There is no `trustable_decisions` read, because the availability set §1 fixes is
three conditions wide and `grantable_decisions`' own rows already satisfy every one of them
that a user is looking at — the listing exists, and §5 makes it name both acts. And there is
no history read beside the standing one, because the reason ADR-0235 §7 needed
`recent_recipient_grants` does not arise: that member exists because *"a user at the ceiling
could hold an **expired** grant occupying a slot, see it in no listing, and have no id to pass
to `revoke_recipient_grant`"*, and a trust record has no ceiling and no expiry, so a record
that is not in the live listing is one that has been revoked and needs no act.

### 3. What a surface shows before it collects the act

> **Normative.** Before it collects the act, a surface renders, **whole and as data
> neutralised for that target on render** (ADR-0042 §4): the canonical destination set the
> record would be over, **in both supplied and canonical forms**, as `core` derived it and
> never as the surface re-derived it; the connected account's identity; the tool the decision
> is about, by the declaration's own identifier and capability; and the instant the decision
> was recorded. That is ADR-0193 §2's rendering floor, read one act over, minus the two
> members that have no referent here — a payload description and an expiry — because this
> record is about a destination set and nothing else (ADR-0238 §1).

> **Normative.** A surface offering the act states, before it collects it, **four facts about
> what the act does**, as facts about this record and naming no future call, no expected
> benefit and no behaviour it cannot promise: that this is **not** the act that decides
> whether the system may talk to this party, which is the recipient grant and a separate
> question (ADR-0238 §1); that after it, what the system composes for this destination may be
> drawn from records it holds about the user rather than from the user's own words alone
> (ADR-0238 §2); that the fact is **prospective and revocable**, takes effect for every later
> request and rewrites no recorded decision (ADR-0238 §1, ADR-0193 §9); and that it carries no
> end date, so it stands until revoked (§2).

> **Normative.** A surface offering the act states, before it collects it, a **fifth** fact
> that is easy to leave out and false to leave implied: **a conversation that has already read
> from a destination it did not trust is not repaired by the act.** ADR-0238 §5's recorded half
> is monotone over a conversation, so what the act changes is what a **later** conversation may
> compose. The surface states it as a fact about how the act takes effect and promises nothing
> about any conversation in progress.

> **Normative.** **ADR-0233 §8's span-value floor is not met by this surface and no surface
> claims it is.** That floor is stated over a surface rendering a `Confirmation` whose
> `egress` is present, which this is not: the subject is a recorded `PermissionDecision`
> carrying a `parameters_digest` rather than argument values, and no future call's bytes exist
> to show. No surface renders a digest as a value, renders a reconstruction, summary, excerpt
> or paraphrase of any call's arguments, or states or implies that the user has been shown
> what any call would send. **A surface that cannot say what a call would send says so**,
> which is ADR-0233 §8's own no-summary clause pointed the honest way, and which ADR-0235 §5
> states for the identical population.

> **Normative.** The honest statement this surface owes about the **future** is stated here
> rather than left to a lane, because it is the one respect in which this act is harder to
> render than ADR-0235's: the trust record widens what may be composed for **calls that have
> not been planned yet**, so no surface can show the user the bytes of what their act admits,
> and none pretends otherwise. What is shown is the destination set and the **class** —
> records this system holds about the user, composed into a query by a model, under the
> per-conversation call budget ADR-0238 §8 fixes — and a surface states the class and stops.
> It does not name a number, quote a budget, estimate a volume or promise a bound.

> **Normative.** The surface renders `planned_with_external_content` under ADR-0181 §6 where
> it renders the decision at all, in all its states, and renders no state of it as a
> detection, a score, or a warning that the call was malicious (ADR-0181 §7, ADR-0193 §2). A
> row on which the act is unavailable for §1's third condition **is still rendered**, with the
> act not offered on it; a listing that silently omitted such a row would be reporting a
> judgement about content it is forbidden to make.

> **Normative.** No surface offers the act attached to an **edit** of anything. There is
> nothing to amend — the act takes an id and transcribes a recorded set — and no lane adds a
> parameter that would make an amendment expressible.

### 4. Listing and revocation

> **Normative.** `standing_destination_trust()` reads `DestinationTrustStore.live` — every
> record that is not revoked, in the store's own order — and takes **no `limit`**, for
> `assistant connections`' and `standing_recipient_grants`' stated reason: a truncated answer
> to *"what do I trust"* is a false answer rather than a partial one. It composes, filters,
> projects, enriches and summarises nothing, and reads no other store.

> **Normative.** `revoke_destination_trust(record_id)` reads `live`, and where no live record
> carries that id returns **`False`**, having written nothing; otherwise it calls
> `DestinationTrustStore.revoke` with that id and the instant of the user's act and returns
> **`True`**. It returns a `bool` and not a record because ADR-0238 §1 declares `revoke`
> *"taking a record `id` and the instant of the user's act"* and declares no return, so a
> member returning a record would either author one — which the engine may not do — or add a
> store member, which that section's exact-surface clause forbids. `forget`,
> `forget_question` and `dismiss_notification` are the shape on this Protocol.

> **Normative.** `revoke_destination_trust` **loses a concurrent revocation gracefully**, and
> the store's own idempotence is what makes it free: two callers may both find the record
> live and both call `revoke`, and ADR-0238 §1 makes that member *"prospective and
> idempotent"*, so the second changes nothing and neither caller is told a falsehood. `False`
> is the honest answer to a caller arriving after the record is gone — by the time that call
> completes the store holds no live record with that id, which is exactly what `False` means
> here — and **the user's recourse succeeded**: the trust they asked to withdraw is withdrawn.
> No lane retries, revokes twice, or reports the loss as a fault.

> **Normative.** An `InvalidDestinationTrustError` raised on any other ground **propagates
> unchanged**, and no lane converts one into `False`. ADR-0238 §1's unknown-id refusal is not
> reachable after a successful live match and is not a case this operation reports.

> **Normative.** Revocation is **never refused** for any count, budget or ceiling, is
> **whole** — no operation narrows a trust record, re-scopes one, extends one or edits one in
> place — and is **prospective**: it takes effect for every later request and rewrites no
> recorded decision, so a search already ruled `ALLOW` stays ruled and a record already
> supplied to a composer is not retracted (ADR-0238 §1, ADR-0193 §9).

> **Normative.** No surface derives liveness from anything but
> `standing_destination_trust()`. A view that has not read it says the state is unread
> (ADR-0177 §6's fifth clause, read one store over), and no surface infers trust from a
> recipient grant, a connection, a `Settings` value, an audit row or a search that succeeded.

> **Normative.** Destination trust and recipient grants are **two vocabularies and never
> one**, as recipient grants and source grants already are (ADR-0235 §7). No operation,
> command, route, view or listing answers one with the other, presents a trust record among
> grants or the reverse, offers a control that revokes across both, or names a combined total.
> A surface may put them on one screen; what it may not do is answer either question with the
> other's records, which is ADR-0177 §6's fourth clause read across a third pair and for its
> reason.

> **Normative.** No user-facing read of `DestinationTrustStore.export` is minted here.
> `export` is what discharges ADR-0004 §6 for this store (ADR-0238 §1) and it reaches no
> operation in this ADR, for ADR-0235 §11's reason: ADR-0186 §9 reserves the bare `assistant
> export` for ADR-0004 §6's whole-installation artifact and **#1502** holds it. §14 defers it
> with that trigger.

### 5. Per channel: the terminal now, the browser by its own decision, voice withheld

> **Normative.** The **command-line surface** carries all of it and is the surface the
> implementing lane ships. **Three** commands are added, **by these names and not by names a
> lane chooses**, in a destination vocabulary distinct from the recipient-grant commands
> ADR-0235 §9 fixed and the source-grant commands ADR-0235 §7 keeps:
>
> - **`assistant trust-destinations <decision-id>`** — the act of §1, taking a decision id
>   from `assistant remember-recipients`' listing or from `assistant decisions`.
> - **`assistant destination-trust`** — the standing listing over
>   `standing_destination_trust`. It takes **no `--limit`**, for §4's stated reason.
> - **`assistant revoke-destination-trust <record-id>`** — the revocation of §4, taking the
>   id the listing renders.

> **Normative.** These names are fixed here rather than left to the lane, for the reason
> ADR-0186 §9 fixed `assistant decisions` and `assistant export-decisions` in terms: *a
> normative decision an operator cannot derive a working command from is one no test can pin*.
> They qualify with **`destination`** because on this surface `grant`, `amend`, `revoke`,
> `grants` and `granted` already name `SourceGrant` and `remember-recipients`,
> `recipient-grants` and `revoke-recipient-grant` already name `RecipientGrant` — ADR-0186
> §1's naming rule, which makes the shorter name right only where the word has one referent,
> coming out the same way a third time. The verb form and the noun form differ as
> `remember-recipients` and `recipient-grants` differ, which is the pair this one is modelled
> on.

> **Normative.** `assistant trust-destinations` states its outcome from the **type of the
> refusal** and never from a message or a read-back, which is `_drive_establish`'s ratified
> shape: on `UntrustableDestinationError` it names which of §1's three conditions failed and
> says nothing was recorded; on `DuplicateDestinationTrustError` it says the destination is
> already one the user chose and names `assistant destination-trust`; on the base
> `InvalidDestinationTrustError` it says no trust was recorded and **names no cause it was not
> given**; on a bare store fault it says the trust store could not be written and that nothing
> was recorded. None of the four propagates as a traceback, and none is rendered as a fault of
> any call.

> **Normative.** `assistant remember-recipients`' listing **names both acts in its next-step
> line, as two acts**, giving the granting form and the trusting form side by side over the
> same decision id and saying that they are two questions and that neither completes the
> other. It performs **no trust read** to do it: the line is a fixed statement of what the two
> commands are, not a rendering of any destination's current state, so no inference and no
> second store read enters the listing. This is what discharges ADR-0238 §1's *"knowing it was
> a second question"* at the point of discovery, and it is the whole of the coupling between
> the two acts.

> **Normative.** **No flag on any command performs the other act.** `--until` stays
> `establish_recipient_grant`'s `expires_at` and nothing else; `--remember-recipients-until`
> on `resume` stays ADR-0235 §2's and gains no sibling here; and `--yes`, which today declines
> to answer any confirmation carrying an egress, **never supplies this act**. No
> non-interactive flag, environment variable, configuration value or scripted default records
> destination trust: it is a decision of the user made while looking at the destination set,
> and a flag that made it standing would be the out-of-call establishment ADR-0193 §2's second
> clause refuses and ADR-0238 §1's *"No configuration sets it"* forbids outright.

> **Normative.** The **browser** is not reached by this decision. ADR-0177 §1's enumeration is
> not widened, none of §2's operations resolves from a browser request, no browser argument
> reaches one, and the gateway makes no call of its own to any of them. A browser surface for
> this act is a **later consumer lane with its own ratified decision**, which widens ADR-0177
> §1's enumeration in its own text — the route ADR-0177 §1's third clause fixes and ADR-0235
> §9 took for the sibling act. It inherits §3's floor and §4's two-vocabulary rule without
> restating them. **Fired** by the lane that takes the browser's confirmation card past
> ADR-0233 §8's floor, which is where the second control would sit.

> **Normative.** **No spoken trust surface is created, and none may be created by reading this
> ADR.** ADR-0207 §2's fixed sentence — `I need you to confirm something on your screen.` —
> remains the whole of what a live confirmation park says on `converse_spoken`, and no spoken
> form of the act, the listing or the revocation is minted. Destination trust is recorded on a
> screen or it is not recorded.

> **Normative.** This ADR states the posture ADR-0199 §3's sixth clause obliges it to state,
> for the content these surfaces render. A `DestinationTrustRecord`, a canonical destination
> set in either form, a connection reference, a connected account's identity, and any
> rendering, excerpt, summary or paraphrase of one are **withheld** from a channel of
> unbounded audience; they are placed as speakable on no such channel, by this ADR or by any
> silence in it. **A `SearchNotServiced` member and a reply composed from it are placed as
> speakable** on such a channel, because §8 fixes the member as a closed vocabulary carrying
> no destination, no account, no query, no figure and no command, and §8's bars are what make
> that placement safe rather than a judgement about any particular reply.

> **Normative.** An ADR that admits a spoken or otherwise audible channel whose audience is
> **bounded** decides in its own text whether the withheld content above is placed as speakable
> there, on ADR-0199 §5's terms and its own. This ADR neither places it nor forecloses that
> ADR.

**Withholding voice costs something real and it is stated rather than minimised**, exactly as
ADR-0235 §9 states it for the sibling act: in a deployment whose only surface is voice, a
user cannot record trust, so every search is composed from their own words alone and no
follow-up search is possible. The alternative — a spoken destination list — discloses which
third parties the owner's assistant talks to into a room for whoever else is in it, which is
the disclosure ADR-0199 exists to refuse. **What voice *does* get from this ADR is the
reply**: §7's explanation is speakable, so a voice-only user is told that a search did not
happen and why, even though the act that would fix it is on a screen.

### 6. The reply says a search did not happen, and that is the clause the owner's amendment moves

> **Normative.** On a turn in which **at least one search servicing recorded a
> `SearchDisposition`**, the composing stage is given one member of §8's closed vocabulary and
> composes an answer that says so. On every other turn it is given nothing, and the assembled prompt is
> byte-identical to what it is today — the same guarantee ADR-0228 §10 makes for its own
> carrier and ADR-0227 §3 for its own, and the clause that keeps a new prompt input from
> silently moving every reply the system composes.

> **Normative.** **The eligibility condition is the disposition's presence and nothing else**,
> and it is stated that way rather than over any account of what happened, because the tree
> already computes it: `ServicedRead.disposition` is `None` on a servicing that yielded records
> into the supply and carries a member on every servicing that did not. A turn on which every
> servicing yielded records carries **no** `SearchNotServiced` member.

> **Normative.** In particular a search that **ran, reached the provider and found nothing**
> carries no member. `SearchRefusal.NO_RESULT` is not a refusal and maps to no
> `SearchDisposition` member (ADR-0231 §13), so the assistant looked, and saying it did not
> would be false. **A search that reached the provider and whose response was then refused —
> unattested, oversized, or refused by the provider — *does* carry one**, and it carries
> `UNAVAILABLE` (§8): records reached no supply, the user has no act, and §9 fixes a statement
> for that member which says the lookup produced nothing usable and **does not say that no
> request was made**.

> **Normative.** **This is a reply and not a notification.** No lane mints a `Notification`, a
> notification kind, a delivery or a poll result for a search that did not happen. ADR-0235
> §8's second clause binds entire — *"a notification is a decision about interrupting the user
> and this ADR takes none"* — and neither does this one.

> **Normative.** The fact does **not** set `TurnOutcome.reply_degraded`, and no lane sets it
> on this account. ADR-0170 §4 fixes the three shapes on which `reply` is `None` and the one on
> which `reply_degraded` is `True`; this decision alters neither, so no clause of ADR-0170 is
> superseded, narrowed or read more widely. A turn that could not search still composed the
> reply it composed.

**Why this clause moves, stated once and not rebuilt.** ADR-0231 §9 refused to tell the
composing stage anything for a good reason and named its own alternatives: a sentence in the
reply, a notification, or nothing at all. ADR-0235 §8 then chose the fourth — a **pull**, a
listing the user can go and look at — and argued it as *"a place the user can look, next to
the one act that changes the answer"*. **What has changed is not the argument but the
mechanism the argument was made over.** In both of those ADRs a refused search was an
inert event on a system where no search could ever succeed: `app/composition.py` recorded in
terms that *"until a surface offers the establishing act (§13) the store is empty, so every
ruling is the one it was before"*. A pull is a coherent design for a mechanism that never
fires. Milestone 31 makes it fire — and once searching is the normal case, a turn that
silently did not search is a reply the user cannot tell from one that did, which is the one
failure a pull cannot address, because a user who does not know to look does not look. The
owner's 2026-09-09 amendment names that gap and this ADR closes it. **ADR-0235 §8's listing
is not replaced**: it stays exactly where it is, and §9 below puts the reply and the listing
in their proper relation — the reply says a lookup did not happen, the surface names the act,
and the listing is where the act is performed.

### 7. The carrier: one member, computed once at the servicing site, carried inside `orchestration`

> **Normative.** The member is computed **at the servicing site**, by the component that
> recorded the `SearchDisposition`, from that disposition and from **three values that site
> already holds** — the `trust_of` answer, the request binding's
> `planned_with_external_content`, and `Settings.search_calls_per_conversation` (§8) — and from
> nothing else. The third is a deployment configuration, constant across every turn and read
> from no record. It is **supplied, not inferred**: no component derives it from the plan,
> from the supply's length, from the reply, from the audit, from a store read of its own or
> from any content whatever.

> **Normative.** The carrier travels **inside `ai_assistant.orchestration`**, from that site
> to the composing stage, as data — the shape ADR-0228 §10 fixes for its own fact and
> ADR-0227 §3 for its own, and the shape `stopped_while_asking` and `hop_reached` already take
> on `Composer.compose`. It adds no member to any Protocol, and it is never recomputed
> downstream.

> **Normative.** **At most one member is carried per turn.** Where a turn holds more than one
> servicing that recorded a disposition, the member carried is the one **earliest in §8's
> declared order** among them, and the others are carried nowhere. **The order and not the
> encounter order decides it**: a member is never overwritten by a later servicing's, and an
> implementation carrying the last one it computed is wrong even where every individual
> mapping is right.

> **Normative.** **A servicing that yields records does not clear a member an earlier one
> produced.** A turn on which one search was refused and a second succeeded still carries the
> first's member, because §6's eligibility is stated over the presence of a disposition and a
> later success does not remove one. No lane makes the carrier conditional on the turn's last
> servicing, on whether the supply ended non-empty, or on whether the reply looks complete. A reply that enumerated a turn's servicings would
> be reporting the system's internal shape, which is the direction ADR-0226 §9's
> counts-and-no-copy reasoning and ADR-0228 §10's *"no count, no duration, no guard name"*
> both refuse.

> **Normative.** The reply is composed by the model from a **fixed prompt fragment per
> member**, written in `ai_assistant.orchestration` and interpolating nothing. No fragment
> carries, and no lane makes a fragment carry, a destination, a host, an origin, a provider
> name, a connection reference, an account identity, a query or any fragment of one, a record,
> a count, a monetary figure, a duration, a budget, a `Settings` field name, a
> `SearchDisposition` value, a record id, a decision id, or a command name. `_STOPPED_ASKING_PROMPT`
> is the shape and its own bar is the model: *"you have not been told any of that."*

> **Normative.** **No lane widens the carrier to free text.** The member is a closed
> vocabulary and the only thing that crosses; a message, a reason string, a provider response
> or a formatted sentence assembled from any of them is refused here, for ADR-0231 §13's
> no-message reason and ADR-0004 §5's.

**One member and not a bare bool, which is where this departs from ADR-0228 §10 and why.**
That section carries a bare fact and argues it: *"One fact and not two, because the user
cannot act on the difference … a reply that named the deadline would invite a retry, and a
retry hits the same bound over the same supply."* Here the user **can** act on the
difference, and the acts are different commands: a recorded question is
`remember-recipients`, a destination not yet chosen is `trust-destinations`, an exhausted
allowance is a new conversation, and a spend ceiling is the operator's. That is exactly the
condition ADR-0228 §10's reasoning is stated over, and it comes out the other way. **What does
not change is the bar on everything else**: the member says which *class of act* is available
and carries no quantity, no name, no cause and no content, so the reply gains a direction and
gains nothing the user could not already have deduced from having asked the question.

### 8. The vocabulary, and the mapping that is total

> **Normative.** `SearchNotServiced` is a `StrEnum` in `core/types.py`, valued by lower-cased
> member name, closed at exactly **eight** members and declared in this order, which is also
> **the precedence order §7 applies**:
>
> 1. **`SEARCH_DISABLED`** — `admit_search` refused the servicing and
>    `Settings.search_calls_per_conversation` is **`0`**, which ADR-0238 §8 defines as *"no
>    search is serviced in any conversation"*.
> 2. **`NOT_ADMITTED`** — `admit_search` refused the servicing under a **positive** bound
>    (ADR-0238 §8, §11).
> 3. **`SPEND_EXHAUSTED`** — a monetary ceiling or an undetermined accounted total refused it
>    (ADR-0194, ADR-0236, ADR-0238 §10).
> 4. **`DECLINED`** — the policy ruled `DENY` on it.
> 5. **`TRUST_MISSING`** — the policy ruled `CONFIRM`, the request's binding carried
>    `planned_with_external_content` `True`, **and** the servicing site's `trust_of` read
>    answered `UNCHOSEN`.
> 6. **`AUTHORISATION_AWAITED`** — the policy ruled `CONFIRM` on a request whose binding
>    carried `planned_with_external_content` `False`, so a decision the establishing act may
>    ride was recorded.
> 7. **`INTERRUPTED`** — the search was begun and stopped before it answered (§10).
> 8. **`UNAVAILABLE`** — every other way a servicing yields no records into the supply,
>    including one whose request reached the provider and whose response was refused.
>
> The vocabulary is **added to and never renamed**, and no implementation or later ADR adds a
> ninth member without the ADR that decides it.

> **Normative.** **`admit_search`'s refusal is two members and not one**, because the single
> statement §9 fixes per member cannot be true of both configurations. ADR-0238 §8 makes `0`
> mean *"no search is serviced in any conversation"*, so a statement pointing a user at a new
> conversation is false on a deployment that has switched searching off; and a statement that
> named neither would leave #2168's exhausted-allowance case with nothing to say. The
> discriminator is the **deployment's own configuration** — a `Settings` value the servicing
> site already holds, constant across every turn — which is ADR-0236 §4's own move: *"The two
> grounds are told apart from the deployment's **own configuration** and never from a per-turn
> record."*

> **Normative.** **`NOT_ADMITTED` asserts that the servicing was not admitted and does not
> assert that this conversation's allowance was consumed.** ADR-0238 §14 makes `admit_search`
> answer `None` on a conversation id that names nothing and on one stamped deleted as well as
> on a bound that is reached, and the site cannot tell those apart. What §9's statement says is
> that the search was not admitted **for this conversation** and that the allowance is per
> conversation — the mechanism ADR-0238 §8 fixes — and it names no quantity, no bound and no
> consumption.

> **Normative.** The mapping from `SearchDisposition` is **total and non-injective, and that
> is the design rather than a compromise**. `SearchDisposition` names *the stage that produced
> the outcome*, for an operator reading an audit (ADR-0231 §9, §13); `SearchNotServiced` names
> *the act that would change it*, for the user reading a reply. Two dispositions with one act
> behind them are one member, and one disposition with two acts behind it is two members. **No
> lane makes this mapping injective**, restores a stage name to it, or reports a
> `SearchDisposition` value to a user.

> **Normative.** The mapping is exactly this and no other:
>
> | `SearchDisposition` | `SearchNotServiced` |
> | --- | --- |
> | ADR-0238 §11's sixteenth member (`admit_search` refused), `search_calls_per_conversation` is `0` | `SEARCH_DISABLED` |
> | ADR-0238 §11's sixteenth member (`admit_search` refused), the bound is positive | `NOT_ADMITTED` |
> | `SPEND_REFUSED` | `SPEND_EXHAUSTED` |
> | `RULING_DENY` | `DECLINED` |
> | `RULING_CONFIRM`, binding carried `planned_with_external_content` `False` | `AUTHORISATION_AWAITED` |
> | `RULING_CONFIRM`, binding carried `planned_with_external_content` `True`, `trust_of` answered `UNCHOSEN` | `TRUST_MISSING` |
> | `RULING_CONFIRM`, binding carried `planned_with_external_content` `True`, `trust_of` answered `USER_CHOSEN` | `UNAVAILABLE` |
> | `DEADLINE_EXPIRED` (ADR-0241 §4) | `INTERRUPTED` |
> | `NOT_CONFIGURED`, `NO_BUDGET`, `COMPOSER_DECLINED`, `COMPOSER_UNAVAILABLE`, `COMPOSER_MALFORMED`, `COMPOSER_TOO_LONG`, `BINDING_FAILED`, `RULING_UNAVAILABLE`, `TRANSPORT_FAILED`, `PROVIDER_REFUSED`, `RESPONSE_TOO_LARGE`, `UNATTESTED`, `SEARCH_FAILED` (ADR-0241 §8) | `UNAVAILABLE` |
>
> That is all **eighteen** members ADR-0241 §8 leaves the enumeration closed at — ADR-0231
> §13's fifteen, ADR-0238 §11's sixteenth, and ADR-0241's two — and every one of them is
> mapped.

> **Normative.** A `SearchDisposition` member minted by a **later** ADR maps to `UNAVAILABLE`
> unless that ADR's own text maps it elsewhere. The default is the least-claiming member —
> §9's rendering for it names no cause and no act — so a member nobody has mapped degrades to
> silence about the reason rather than to a wrong reason.

> **Normative.** **No member of this vocabulary asserts *why* a ruling was not an `ALLOW`,
> and no lane restores such an assertion.** A `RULING_CONFIRM` does **not** establish that a
> recipient grant is missing: ADR-0236 §4 fixes the shipped default in terms — with
> `web_search_cost_per_call` unset the unknown-cost floor fires beside the disclosure floor,
> so *"the `RecipientGrants` seam is consulted **zero** times whatever grants exist"* and *"no
> standing grant is consulted and no search can be `ALLOW`ed"* — and a configured
> `deny_at_risk` or `deny_at_reversibility` supplies a second independent ground. The site's
> permitted inputs (§7) cannot separate those from an absent grant, so **this ADR states each
> member over what its inputs establish and never over a cause they do not.**

> **Normative.** **`AUTHORISATION_AWAITED` asserts exactly two things, both established.**
> That a `CONFIRM` was recorded rather than the search made — ADR-0231 §9 records every
> outcome — and that the decision it was recorded under is one the establishing act **may
> ride**: its ruling is a `CONFIRM`, it carries no `step_id` and no `execution_id` (ADR-0231
> §6), nothing resolves it (*"It resolves in no turn"*), and its binding is an `EgressBinding`
> whose `planned_with_external_content` is `False` — ADR-0235 §3's conditions, satisfied by
> construction rather than by a read. It asserts **nothing about which floor fired**, nothing
> about what grants stand, and nothing about what answering will achieve.

> **Normative.** **`TRUST_MISSING` likewise rests on a value the site read and not on the
> ruling.** `trust_of` answering `UNCHOSEN` establishes on its own that ADR-0238 §5's
> closed-loop condition cannot be met for this destination and that the trust act is one the
> user has not performed. It does **not** establish that trust is the *only* thing missing,
> and §9 bars the statement from saying so.

> **Normative.** **Where the binding carried `planned_with_external_content` `True` and
> `trust_of` answered `USER_CHOSEN`, the member is `UNAVAILABLE`** — the member that names no
> cause and no act — and it is neither `AUTHORISATION_AWAITED` nor `TRUST_MISSING`. The
> destination is already chosen, so the trust act is not the answer; and ADR-0238 §5's
> **recorded** half is monotone over the conversation, so nothing established now repairs it
> and the decision that records the refusal is itself not one ADR-0235 §3 offers the act on. **Naming an act that cannot help is worse than naming none**, and the permitted
> inputs (§7) cannot establish which of §5's conditions failed, so this ADR takes the
> fail-safe direction rather than guessing. §14 defers the finer explanation with its
> trigger.

> **Normative.** **The two inputs are read at the site and never reconstructed.**
> `trust_of`'s answer is the one ADR-0238 §5 already obliges the servicing site to take, read
> at the position §5 fixes and not a second time; `planned_with_external_content` is read from
> the binding the request carried. No component re-reads the trust store to render a reply, and
> no renderer asks either question for itself.

**Eight members chosen by what the user can do, and the count is argued rather than assumed.**
Five of them name an act the user or the operator can perform and each act is different;
`DECLINED` and `INTERRUPTED` name something that happened to the request rather than something
available, and their recourses are to change a threshold and to ask again; `UNAVAILABLE` is
the deliberate residue, and it is one member rather than thirteen because none of the
situations behind it gives the user anything to do — including the closed-loop case, where an
act exists but is not one that would help. Collapsing further would merge acts; splitting
further would either report the system's stages, which is `SearchDisposition`'s job and the
audit's, or assert a cause §7's inputs cannot establish, which is what round 2 of this ADR's
review found an earlier draft doing.

### 9. `TurnOutcome` carries the same member, and the command name is on the surface and not in the reply

> **Normative.** `TurnOutcome` gains exactly one field, **`search_not_serviced`**, typed
> `SearchNotServiced | None` and defaulting to `None`, and its docstring names this ADR as the
> decision that added it. It carries **the same member §7 computed, by value, and never a
> second computation**. That is ADR-0235 §4's move and ADR-0197's before it — a widening
> rather than a change, since ADR-0170 §4's three `reply`-`None` shapes and its one
> `reply_degraded` shape are untouched — and neither of those recorded a supersession of
> ADR-0170 for the identical move, so this one records none either.

> **Normative.** `search_not_serviced` is `None` on **every** outcome of a turn that serviced
> no search or serviced every search it asked for: every such `converse`,
> `converse_streaming` and `resume`, and ADR-0198 §1's **restatement**, which drives nothing
> and searches nothing. That adds a value to ADR-0198 §2's enumeration without changing any
> value it fixes — `turn`, `routed`, `reply`, `reply_degraded` and `step` carry there exactly
> what that clause says they carry, and `None` is the true value of a member describing
> something the restatement did not do.

> **Normative.** `SpokenTurn` gains **nothing**, and no lane adds a second field for this fact
> anywhere. On `converse_spoken` the spoken reply is the whole of what the user is told, which
> is §5's placement posture met exactly: the reply is speakable and the act is not.

> **Normative.** The field exists so that **a surface names the act deterministically**, and
> that is the whole of what it is for. A surface renders, beside the reply and never in place
> of it, one fixed statement per member, naming: for `AUTHORISATION_AWAITED`, that the search
> was **put to the user as a question instead of being made** and that a decision is recorded,
> with `assistant remember-recipients` as the listing of decisions they can still answer; for
> `TRUST_MISSING`, that the destination is not one the user has chosen, and `assistant
> trust-destinations` with **`assistant decisions`** as where the decision id is read; for
> `SEARCH_DISABLED`, that searching is switched off in this deployment and that it is an
> operator setting, **naming no user act**; for `NOT_ADMITTED`, that this conversation did not
> admit the search and that the allowance is per conversation, so a new conversation has one of
> its own — **asserting neither that this conversation's allowance was consumed nor that a new
> conversation will succeed**; for `SPEND_EXHAUSTED`, that a spend ceiling refused it and that
> it is an operator setting; for `DECLINED`, that the search was declined when it was ruled on;
> for `INTERRUPTED`, that the search was begun and stopped; and for `UNAVAILABLE`, that the
> lookup produced nothing the turn could use, **naming no cause and no act**. The exact wording
> is the lane's; what is fixed is which command each names and that `UNAVAILABLE` names none.

> **Normative.** **No statement says that performing the act it names will make the next
> search happen**, and none says why a ruling was not an `ALLOW`. `AUTHORISATION_AWAITED` does
> not say that no standing authorisation covers the recipients; `TRUST_MISSING` does not say
> that trust is the only thing missing; neither names a floor, a threshold, a `Settings` field
> or a configuration. That is ADR-0235 §8's third clause — a surface *"does not state that the
> turn would have answered differently … that a search would have succeeded, or that anything
> is owed"* — binding on these statements as it binds on that listing, and §8's inputs are why
> it has to.

> **Normative.** **`TRUST_MISSING`'s statement says nothing about what the query was composed
> from**, and no lane restores such a sentence. The two `trust_of` reads ADR-0238 §5 admits
> are separated by a window that ADR sets out and ADR-0238 §16 defers closing, so a
> revocation landing between them leaves a supply that *was* composed over records and a
> build-time read that answers `UNCHOSEN`. A statement asserting the composition's inputs
> would be false in exactly that case, and the surface has not been told them. What the
> statement says is that the destination is not one the user has chosen and that the search
> was not made.

> **Normative.** **`TRUST_MISSING`'s statement says that recording trust changes what a
> *later* conversation may compose, and does not promise it changes this one.** ADR-0238 §5's
> recorded half is monotone over a conversation: once a record has arrived from an `UNCHOSEN`
> destination, that conversation *"fails the recorded half for every later turn"*, and a trust
> record established afterwards does not lift it. A statement implying otherwise would send the
> user to perform an act and then watch the same conversation refuse the same search — now as
> `UNAVAILABLE` (§8), which names no act at all. §15 owes the arm that walks exactly that
> sequence.

> **Normative.** **`TRUST_MISSING`'s statement names `assistant decisions` and not
> `assistant remember-recipients` as where the decision id is read**, and the difference is
> load-bearing rather than stylistic. The decision recording a `TRUST_MISSING` refusal carries
> `planned_with_external_content` `True`, so ADR-0235 §3's seventh condition excludes it from
> `grantable_decisions` **and** §1's third condition above excludes it from the trust act; and
> the earlier decision the user granted from has been resolved, so ADR-0235 §3's fourth
> condition has taken it out of that listing too. `assistant remember-recipients` can therefore
> be empty at exactly the moment its guidance is followed. **`assistant decisions` is
> ADR-0186 §1's bounded read of the whole trail**, it carries resolved decisions, and the
> earlier decision remains a valid subject of the trust act because §1 makes the act
> indifferent to a decision's ruling and resolution. §15 owes the arm.

> **Normative.** `assistant remember-recipients`' listing keeps naming both acts (§5) and is
> the right route on the **first** refusal, where the decision is unanswered and its binding
> carries `planned_with_external_content` `False`. No lane reads the clause above as removing
> that line or as making one of the two listings the only route; what is fixed is that the
> statement rendered for `TRUST_MISSING` names the listing that always has the id.

> **Normative.** **None of the eight statements carries** a destination, a host, an origin, a
> provider name, a connection reference, an account identity, a query or any fragment of one,
> a record, a count, a monetary figure, a duration, a budget, a `Settings` field name or a
> `SearchDisposition` value. §7's bar on the prompt fragments and this bar are one rule stated
> at the two render sites it has to hold at.

> **Normative.** **The command name is not in the reply and the reply is not in the surface
> statement**, and the split is decided rather than incidental. A command name in a
> model-composed reply is wrong twice over: it would reach a browser and a voice channel where
> no terminal exists, and it would be a string a model may paraphrase, truncate or invent.
> A surface statement that restated the answer would be composing a reply in `interfaces/`,
> which golden rule 3 refuses. So the model says **what was not done** and the surface says
> **what would enable it**, and each says only the half it can say truthfully.

> **Normative.** Rendering a fixed statement per enum member is **presentation and not
> business logic**, and `_render_recipient_grant_outcome`'s five statements over
> `RecipientGrantNotEstablished` are the ratified precedent (ADR-0235 §9). No adapter reads a
> store, joins a row, computes a member, or renders a statement for a member it was not given.

> **Normative.** A surface that renders **no** statement for a member is a surface that has
> not implemented this section, not a permitted degradation; the browser, until its own lane
> (§5), renders neither the statement nor the reply's absence of one, because it renders the
> turn exactly as it does today and the field it now receives is one it ignores.

### 10. The seam with ADR-0241, stated in terms

> **Normative.** **ADR-0241 decides when a search is interrupted and when the searcher
> failed; this ADR decides what the user is told in each case.** ADR-0241 — ratified and
> merged on 2026-09-09, and the base this ADR now sits on — decides how a declared bound
> reaches `WebSearcher.search`, that an expiry is reported as `DEADLINE_EXPIRED` rather than
> `TRANSPORT_FAILED`, that a fault raised out of the seam after the ruling is `SEARCH_FAILED`,
> and how an interrupted call is accounted. **This ADR takes none of that** and no lane cites
> it toward a deadline, a `WebSearcher` argument, a cancellation posture or an accounting rule.

> **Normative.** **Both of ADR-0241's members are mapped here, by name, in §8's table** —
> `DEADLINE_EXPIRED` to `INTERRUPTED` and `SEARCH_FAILED` to `UNAVAILABLE` — rather than left
> to §8's default or to a later lane. That is the seam this section fixed while ADR-0241 was
> unlanded, discharged now that its text is ratified: it names the members, so this ADR maps
> them, and neither ADR carries a clause the other has to complete. **`SEARCH_FAILED` is
> `UNAVAILABLE` and not `INTERRUPTED`** because ADR-0241 §8 makes it *"the searcher itself
> raised a fault after the ruling"* — a store, ledger or authorisation fault the user has no
> act for — while an expiry is a search that was begun and stopped, which is what
> `INTERRUPTED`'s statement says.

> **Normative.** The implementing lane of **this** ADR implements no producer for either
> member, no timeout, no deadline and no cancellation: `DEADLINE_EXPIRED` and `SEARCH_FAILED`
> are ADR-0241's implementing lane's to emit, and this lane's arms construct the dispositions
> directly (§15). A lane that found itself needing to decide when a search is late has left
> this ADR's fence.

**The two ADRs were written in parallel and neither had to complete the other, which is what
the seam bought.** ADR-0241 needed a member to map to and a sentence for it; this one needed
the disposition names and nothing else. The alternative — ADR-0241 adding a
`SearchNotServiced` member in its own text — would have opened a vocabulary this ADR closes
at eight to an ADR deciding a different question, and left the two racing to define one
enumeration. As it fell out ADR-0241 merged first, so §8's table names its members outright
and §8's default rule stands unused, waiting for the nineteenth disposition rather than for
this one.

### 11. The audit, `PROTOCOL_VERSION`, and the versions that do not move

> **Normative.** **No second audit, no second event key and no new emission point.** ADR-0226
> §9, ADR-0231 §13 and ADR-0238 §11 bind entire: the one `INFO`-level structured event per
> turn under the one fixed key `turn_read_request` carries what those sections say it carries,
> `servicings[].disposition` stays the `SearchDisposition` value, and **`SearchNotServiced` is
> not written to it**. A member computed for a user is not a second spelling of a fact the
> audit already records for an operator, and writing both would make the two drift.

> **Normative.** **The establishing act records no `PermissionDecision`, seeks no ruling from
> `ActionPolicy` and emits no audit event.** It sends nothing, so there is no egress to rule
> on and nothing for the permission trail to hold. **The record itself is the audit**: a
> `DestinationTrustRecord` carries `established_at`, `revoked_at` and the destination set, and
> `DestinationTrustStore.export` answers every stored record, revoked ones included, in a
> stable order — which is what ADR-0238 §1 says that member exists for. No lane adds a trail
> row, a connection act or a second log beside it.

> **Normative.** The lane implementing §2 moves **`PROTOCOL_VERSION` by one from the value the
> constant carries at the moment the lane lands**, in the same change, and records the ground
> in the constant's own commentary as every prior move has. ADR-0124 §9's first limb obliges
> it twice over and the entry records both: the promoted method set grows by **three**, and a
> **wire-carried `core` type gains a member** — `TurnOutcome` gains `search_not_serviced`,
> which crosses on every turn call's result payload. Either ground obliges the move alone.

> **Normative.** **This ADR fixes no number.** `PROTOCOL_VERSION` reads `31` on `origin/main`
> at `2c8aebfc` and lane B1 of batch #2178 is scheduled to move it to `32` ahead of this
> lane, so a figure written here would be a fact about a tree that moves before the lane does.
> The rule is that the lane reads the constant *at the moment it lands* and moves it by one,
> which is ADR-0235 §10's rule verbatim and ADR-0240 §11's practice. No lane reads this clause
> as licence to skip the move, to fold two grounds into one entry, or to write a number without
> having read the one below it.

> **Normative.** **Nothing else under `wire/` changes.** The connect exchange gains no member,
> no frame's encoding changes, no `FrameKind` is added, no codec entry is registered, and a
> result payload takes the shape of the method's own declared return annotation (ADR-0085
> §10) — so `DestinationTrustRecord` and `SearchNotServiced` cross without a second
> declaration and nothing transcribes either into a wire-side schema. `wire/errors.py` derives
> an error code from the class name, so the two new error classes need no registration.

> **Normative.** Peers at different versions do not interoperate and no lane adds a
> compatibility shim, an optional-member negotiation, a per-member capability flag or a lenient
> decode to make them. ADR-0084 §3's exact-match handshake is the mechanism and the refusal
> naming both versions is the intended user-visible outcome.

> **Normative.** **No stored-record version moves**, because this ADR adds no record shape.
> `ConversationExport.schema_version` stays at **2** (ADR-0238 §16 keeps the search draw as the
> store's own row state and this ADR does not present it); `Conversation`, `ConversationTurn`,
> `PermissionDecision`, `RecipientGrant` and `DestinationTrustRecord` are untouched; and the
> durable format of the trust store is lane B1's under ADR-0238 §1 and is not moved here. A
> lane that finds itself moving one has left this ADR's fence.

> **Normative.** `RoutableOperation` gains no member and ADR-0177 §1's browser enumeration is
> not widened (§5), so the gateway's surface is the same size after this ADR as before it.

### 12. What this ADR does not decide, each with its reason

> **Normative.** Beyond the marked clauses §16 enumerates, this ADR decides nothing. It
> registers no tool, designates no seam, adds no `DestinationProtocol` member, adds no
> `Settings` field, mints no error class but the two §2 names, and attests, relaxes or adds no
> condition of ADR-0017 §3 or ADR-0154 §4.

> **Normative.** It decides **no fact about any destination** and no rule about how one is
> judged. ADR-0238 §1 binds entire: the fact is set by a recorded act of the user and by
> nothing else, no model output ever sets it, raises it or is consulted about it, no component
> infers it by inspecting a destination, a host, a response or any content, and absence reads
> `UNCHOSEN`. Nothing in this ADR is cited toward a third `DestinationTrust` member.

> **Normative.** It decides nothing about `SourceGrant`, `SourceGrants` or `SourceGrantStore`,
> and nothing about `RecipientGrant`'s own act. ADR-0097 §7 stands verbatim, ADR-0193 §§1–12
> stand as given, and ADR-0235 §§1–7 and §§9–14 stand as given — in particular §7's
> two-vocabulary rule, which this ADR extends to a third vocabulary rather than moving.

> **Normative.** It decides nothing about the per-conversation call budget, the monetary
> ceiling, the spend allowance, or the load-time refusals that bind them. ADR-0238 §8, §9 and
> §10 own all four, **#2116** stays where §9 put it, and §15's arms over them assert the
> *rendering* of an outcome those sections decide and never the outcome itself.

> **Normative.** It decides nothing about how a search is bounded in time, interrupted,
> cancelled or accounted when it is (§10), and nothing about `WebSearcher`'s signature.

> **Normative.** It decides nothing about detection (#75), a span's origin within the
> assistant's own store (#1154), residency (#95), or the unbounded-read question **#1551**
> asks of the grant stores, which `DestinationTrustStore.live` now joins as a third store with
> an unbounded read and no bound on it. None is touched and no clause here is cited toward one.

> **Normative.** It decides nothing about what a **deployment** should trust, recommends no
> destination, and ships no default: `DestinationTrustStore` is empty on a fresh deployment and
> stays empty until a user performs the act.

### 13. What the implementing lane owes

> **Normative.** The lane is **one PR** over `core/protocols.py` (three members),
> `core/types.py` (`SearchNotServiced`, one `TurnOutcome` field), `core/errors.py` (two
> classes), the durable trust store and its canonical fake and conformance suite (the
> subclass, below), `orchestration/` (the engine members, the servicing-site computation, the
> carrier and the prompt fragments), `interfaces/cli.py` (three commands, the four refusal
> renderings, the eight statements, the `remember-recipients` next-step line),
> `wire/client.py` and `wire/envelope.py` (the three `RemoteEngine` methods, the constant, the
> log entry), and their tests. **It lands after lane
> B1 and lane B2 of batch #2178**, because `DestinationTrustStore`,
> `InvalidDestinationTrustError`, `DestinationTrustRecord` and ADR-0238 §11's sixteenth
> disposition are theirs and every clause here is stated over them.

> **Normative.** **`app/composition.py` passes the `DestinationTrustStore` face to the
> engine** and to nothing else, and the store is constructed there and nowhere else (ADR-0238
> §14). No `interfaces/` module imports it, and `uv run lint-imports` is what keeps that true.

> **Normative.** **The lane extends `DestinationTrustStore`'s conformance suite by exactly two
> arms, and extends the canonical fake and the durable store to satisfy them**: that
> `record` raises `DuplicateDestinationTrustError` where a record duplicates a **live**
> record's destination set, and that it raises the base `InvalidDestinationTrustError`
> unchanged on the duplicate-`id` and empty-set grounds. That is what §2's supersession of
> ADR-0238 §1's refusal type entails, and it is owed **at the suite** rather than at an engine
> test because a store implementation raising the base class on the third ground would pass
> every engine test against a different store and still make §5's *already chosen* rendering
> unreachable — the failure §2's read-from-the-type clause forbids repairing by inference.

> **Normative.** **That is the whole of what the lane changes in the triad.** It adds **no
> member** to `DestinationTrustStore`, widens no argument, changes no return, moves no check
> out of `record`'s atomic operation and weakens no assertion the suite already carries —
> ADR-0238 §1's exact-surface clause and its atomicity clause both bind entire, and a lane
> touching either has changed ADR-0238 rather than implemented this. The suite is lane B1's
> and this lane is a **second** contributor to it, in the one scope this ADR's header records.

> **Normative.** The lane also owes `AssistantEngineContract` arms for the three new members,
> beside the five ADR-0235 §12 added.

> **Normative.** The lane **reads `trust_of` once**, at the position ADR-0238 §5 fixes, and
> carries its answer to §8's computation as data. It does not take a second read to render a
> reply, does not move §5's read earlier to make the computation convenient, and does not
> widen §5's read-to-ruling window — which ADR-0238 §14 makes the reviewing lane's own check
> rather than something taken on trust.

> **Normative.** The **eight** prompt fragments and the **eight** surface statements are
> **written out, one per member, as literals**, and neither is assembled from a member's value,
> its name, a format string over the enumeration, or a mapping a later member would silently
> join. A member added without its two texts is a member with no rendering, and §8's closure at
> eight is what makes that a review question rather than a runtime one.

> **Normative.** The lane **files an issue rather than growing** for anything it finds outside
> this fence, and `CONTRIBUTING.md` → "Triage every finding" is the rule. In particular a
> browser control for either act, a spoken form of either, an expiring trust record and a
> user-facing export are §14's and are not this lane's to add.

### 14. Deferred, by name, each with what fires it

- **A browser surface for the trust act, its listing and its revocation.** ADR-0177 §1's
  enumeration stays closed (§5). **Fired** by the consumer lane that takes the browser's
  confirmation card past ADR-0233 §8's floor, which is where the second control would sit, and
  which widens that enumeration in its own ratified text. **Not** fired by a lane finding the
  terminal inconvenient.
- **A spoken form of the act, the listing or the revocation.** **Fired** by an ADR admitting a
  channel of **bounded** audience that places this content as speakable on ADR-0199 §5's
  terms (§5). Not fired by a deployment whose only surface is voice.
- **An expiring `DestinationTrustRecord`, and any `--until` on the trust act.** ADR-0238 §1
  fixes the record at five fields with no expiry, so this is a `core/types.py` change against
  that ADR's exact-shape clause. **Fired** by an ADR that decides trust should lapse, with a
  measurement or a policy behind it. Not fired by symmetry with `RecipientGrant`, which is the
  reasoning §2 refuses.
- **A user-facing export of the trust store.** `DestinationTrustStore.export` discharges
  ADR-0004 §6 and reaches no operation here. ADR-0186 §9 reserves the bare `assistant export`
  for ADR-0004 §6's whole-installation artifact and **#1502** holds it. **Fired** with that
  lane.
- **A ninth `SearchNotServiced` member.** §8 closes the vocabulary at eight. **Fired**
  by an ADR with a user act that none of the eight names. Not fired by a lane wanting a finer
  reason, which is reporting the system's stages by another name.
- **A typed account of *why* a ruling was not an `ALLOW`.** §8 states each member over what
  its inputs establish precisely because a `RULING_CONFIRM` does not say which floor fired
  (ADR-0236 §4), and the site may not read the `RecipientGrants` seam for itself — ADR-0193 §7
  puts the check point at `ActionPolicy.decide` and offers the seam to no one else. Closing it
  would mean a carrier on the ruling saying which floor or threshold produced it, which is a
  `core/types.py` change on ADR-0021 §3's and ADR-0193 §7's ground rather than this ADR's.
  **Fired** by the ADR that decides a ruling should say why. Not fired by a lane wanting a
  sharper sentence, which is the inference §8 refuses.
- **A finer explanation of a closed-loop refusal.** §8 routes a `RULING_CONFIRM` on a request
  with `planned_with_external_content` `True` and a `USER_CHOSEN` destination to `UNAVAILABLE`,
  which names no cause, because the two permitted inputs cannot say which of ADR-0238 §5's
  conditions failed and no act the user can perform repairs the recorded half. **Fired** by an
  ADR that decides a conversation's provenance footing is a thing to show the user — which
  would need a third input at the site and a member with an honest recourse behind it. Not
  fired by a lane finding `UNAVAILABLE` unhelpful in that case, which is the honest answer
  rather than a gap.
- **A bounded or filtered read of the trust store, and a read that answers "is *this*
  destination trusted?" for a row a surface is rendering.** §4's listing is `live` and nothing
  else; §5 discharges discovery with a fixed next-step line at no read; and §9 sends a
  `TRUST_MISSING` user to `assistant decisions` rather than to a filtered listing. Closing it
  would take a member on `AssistantEngine` taking a `CanonicalDestination` sequence.
  **Fired** by a measurement that users perform the grant act and not the trust act, or that a
  real user cannot find an eligible decision in `assistant decisions` — which is where §9's
  recovery journey puts them and where the cost of not having this read lands. Not fired by a
  lane finding the fixed line blunt.
- **Telling the user *which* servicing of a turn did not land, or how many.** §7 carries one
  member per turn. **Fired** by an ADR that decides a turn's search shape is a thing to show
  the user, which is the same question ADR-0238 §16 defers for the draw. Not fired by an
  implementing lane finding one member coarse.
- **Anything about detecting, bounding or accounting an interrupted search** (§10). ADR-0241's.
- **A per-conversation elapsed-time bound, a rolling window for the call budget, a monetary
  per-conversation bound and #2116.** ADR-0238 §16's entries, inherited whole and not
  reopened here.
- **A durable record of the query that left.** ADR-0231 §19 defers it, ADR-0238 §16 inherits
  that deferral whole, and so does this ADR: nothing here retains a query, and §7's and §9's
  bars are what keep one out of a reply.

### 15. The representative-input tests this decision owes

> **Normative.** Each arm below is a test the implementing lane owes, over the **production**
> engine, the **production** servicing path and the **production** renderers, and not over a
> restatement of the rule in a test double. Where an arm names a reply, the assertion runs the
> **real** composing renderer, which is ADR-0227 §3's own bar — *"the test that says so runs
> the real renderer"* — and not a fixture asserting that a flag was set.

> **Normative.** The five arms below are **batch #2178's pre-registered L2 scenarios, pinned
> deterministically**. Each is stated there as a live-hub journey; each is owed here as a
> deterministic arm with a stub search origin, a seeded store and a fixed clock, and §15's
> last clause says what only live QA can add.
>
> - **Arm 1 — the positive path.** A connection reference and origin configured; a first
>   search recorded `RULING_CONFIRM`; the recipient grant established through
>   `establish_recipient_grant`; trust established through `establish_destination_trust` over
>   the same decision; then **two turns of one conversation each service a search**, the
>   second composed over records rather than the utterance alone. Asserts: the audit's
>   `servicings[].disposition` is `None` on both, no confirmation is parked, and
>   `TurnOutcome.search_not_serviced` is `None` on both — which is §6's byte-identity
>   guarantee made checkable.
> - **Arm 2 — missing authority, both kinds, and the discrimination stated as three fixtures
>   rather than two.** Each fixture fixes its grant state and its request's
>   `planned_with_external_content` explicitly; they are not variations of one input.
>   **(a) No grant, a first search:** the binding carries `planned_with_external_content`
>   `False`, `disposition` is `RULING_CONFIRM`, the decision **is** in `grantable_decisions`,
>   the carried member is **`AUTHORISATION_AWAITED`**, the reply states a lookup did not
>   happen, and the surface names `assistant remember-recipients`. **(a2) A grant *standing*,
>   an utterance-only search, and `web_search_cost_per_call` unset**, so ADR-0236 §4's
>   unknown-cost floor produces the same `RULING_CONFIRM`: the carried member is
>   **`AUTHORISATION_AWAITED`** again, and the statement rendered **does not say that no
>   standing authorisation covers the recipients** — the arm that pins §8's
>   states-what-its-inputs-establish rule against the one configuration that falsifies the
>   easier reading. **(b) Grant, no trust
>   record, a follow-up search:** the binding carries `planned_with_external_content` `True`,
>   `trust_of` answers `UNCHOSEN`, `disposition` is `RULING_CONFIRM`, the carried member is
>   **`TRUST_MISSING`**, and the surface names `assistant trust-destinations` and `assistant
>   decisions`. **(c) Grant *and* trust, a follow-up search the closed-loop condition refuses
>   for another reason:** the binding carries `planned_with_external_content` `True`,
>   `trust_of` answers `USER_CHOSEN`, `disposition` is `RULING_CONFIRM`, and the carried
>   member is **`UNAVAILABLE`**, whose statement **names no act**. **(b) and (c) differ in the
>   `trust_of` answer alone**, which is what makes that discrimination the subject of the test
>   rather than a coincidence; (a) differs from both in the binding's footing, which §8 makes
>   the discriminator it is.
> - **Arm 2b — the turn-wide precedence and retention rule, over more than one servicing.** A
>   turn whose servicings record, in this encounter order, `SPEND_REFUSED` and then
>   `COMPOSER_DECLINED` carries **`SPEND_EXHAUSTED`** and not `UNAVAILABLE`, which a
>   last-computed-wins implementation fails while passing every single-servicing arm above.
>   **And the reversed order is a required arm and not an optional one**: a turn recording
>   `COMPOSER_DECLINED` and *then* `SPEND_REFUSED` carries **`SPEND_EXHAUSTED`** too, which a
>   first-computed-wins implementation fails — an implementation assigning only while the
>   carrier is `None` passes every other arm here, so without this one the precedence rule is
>   untested in the direction it is most likely to be got wrong. A turn whose first search is
>   refused and whose second **succeeds** still carries the first's member. All three are
>   asserted on the production servicing path with the dispositions produced rather than
>   injected, and each is asserted at **both** renderers.
> - **Arm 2c — the trust act does not repair the conversation it was prompted by.** The
>   recovery journey §9 names, walked to its end: grant, a granted search that returns external
>   records from an `UNCHOSEN` destination, a follow-up refused as **`TRUST_MISSING`**,
>   `grantable_decisions` observed **empty**, the earlier resolved decision found through
>   `recent_decisions`, the trust act performed on it — and then **the same follow-up retried
>   in the same conversation**, asserting it is still refused and now carries **`UNAVAILABLE`**
>   (ADR-0238 §5's recorded half being monotone), while the **same** follow-up in a **fresh**
>   conversation is serviced. The arm also asserts that the statement rendered for
>   `TRUST_MISSING` said the act changes a later conversation and did not promise this one.
> - **Arm 3 — revoked authority, both kinds.** (a) `revoke_recipient_grant`, then the next
>   search records `RULING_CONFIRM` and `recent_recipient_grants` shows the revoking record.
>   (b) `revoke_destination_trust`, then the second search of a turn is refused, the carried
>   member is `TRUST_MISSING`, and **an `ALLOW` recorded before the revocation is unchanged**
>   — which is §4's prospectivity clause asserted rather than assumed.
> - **Arm 4 — exhausted allowance, and spend kept distinct.**
>   `search_calls_per_conversation=1` yields ADR-0238 §11's sixteenth disposition on the third
>   turn and the member **`NOT_ADMITTED`**, whose statement asserts **no** consumed quantity;
>   `=0` refuses every search before the composer and yields **`SEARCH_DISABLED`**, whose
>   statement names **no user act** and does not point at a new conversation; a servicing whose
>   conversation is stamped deleted before admission also yields `NOT_ADMITTED` and the same
>   statement, which is the arm that pins §8's no-consumption rule against the case that
>   falsifies the easier wording; and a spend refusal yields `SPEND_REFUSED` and the
>   **distinct** member `SPEND_EXHAUSTED`, with a distinct statement. The arm asserts the four
>   are not collapsed.
> - **Arm 5 — the load-time refusal reaches the user as a configuration fault.** A
>   configuration setting `web_search_cost_per_call` and an ADR-0194 period ceiling without
>   `world_spend_unknown_allowance` raises `ConfigurationError` naming the field at `Settings`
>   load (ADR-0238 §10). **What this lane owes is the rendering**: the command's error boundary
>   states it as a configuration fault naming the field, at a controlled exit code, and
>   **never** as a search refusal, a `SearchNotServiced` member or a reply. The refusal itself
>   is ADR-0238 §10's and lane B1's.

> **Normative.** Beside the five, the lane owes: an arm per §1 availability condition, each
> asserting `UntrustableDestinationError` and that **no store was written**; an arm that the
> act succeeds on a decision whose confirmation has already been **answered**, which is the
> ordering trap §1 exists to close; **the recovery journey §9 names — grant, then a follow-up
> refusal, then `grantable_decisions` observed *empty*, then the earlier resolved decision
> found through `recent_decisions` and the trust act performed on it**; an arm that
> `DuplicateDestinationTrustError` is raised and rendered as *already chosen* on a second act
> over one live set; an arm that `revoke_destination_trust` answers `False` for an unknown and
> for an already-revoked id and writes nothing; an arm that the mapping table in §8 is
> **total over all eighteen `SearchDisposition` members**, failing if a member is added without
> a mapping; an arm that a turn whose only search returned `SearchRefusal.NO_RESULT` carries
> **no** member and one that a turn whose search recorded `UNATTESTED` carries `UNAVAILABLE`
> and renders a statement that **does not say no request was made**; **an arm in which trust
> is revoked between ADR-0238 §5's two reads, asserting that the carried member is
> `TRUST_MISSING` and that the statement rendered asserts nothing about what the query was
> composed from**; an arm that `search_not_serviced` is `None` on a restatement (ADR-0198 §1);
> and an arm per member that the reply and the surface statement carry **no** destination,
> host, query, count, figure, duration or `Settings` name — asserted over the rendered bytes,
> not over an intention.

> **Normative.** **No arm asserts that a model produced particular words.** What is asserted
> of the reply is that the fixed fragment reached the assembled prompt and that the prompt on
> a turn carrying no member is byte-identical to today's, which is ADR-0228 §10's own testable
> shape. The eight **surface** statements are asserted over their rendered bytes, because
> those are the system's own words.

**What only live QA can show, stated so that nobody reads the arms as the whole exit.** That
a real provider, reached over a real connection through a real grant and a real trust record,
returns results a real planner follows up on; that the two-command journey is one a person
who has not read this ADR can complete from the listing's next-step line alone; that the
model's reply, over a real completion rather than a recorded one, says the lookup did not
happen without inventing a reason; and that the whole of it holds against the deployed hub at
the moved protocol version. Batch #2178's early live journey (**#2165**) is where the first
of those is measured, and the milestone's QA pass is where the rest are.

### 16. Scope, and what this records against earlier ADRs

> **Normative.** This ADR partially supersedes **four** ratified ADRs and amends none:
> ADR-0231 in one scope, ADR-0235 in one, ADR-0228 in one, and ADR-0238 in one. Each is named
> on that ADR's `Status` line and in its appended dated note under ADR-0082 §1 and §2. **No
> other ADR's text moves**, and in particular ADR-0004, ADR-0015, ADR-0018, ADR-0021,
> ADR-0042, ADR-0060, ADR-0065, ADR-0070, ADR-0074, ADR-0084, ADR-0085, ADR-0089, ADR-0097,
> ADR-0124, ADR-0146, ADR-0148, ADR-0150, ADR-0152, ADR-0154, ADR-0155, ADR-0170, ADR-0177,
> ADR-0178, ADR-0181, ADR-0184, ADR-0186, ADR-0193, ADR-0194, ADR-0197, ADR-0198, ADR-0199,
> ADR-0203, ADR-0207, ADR-0217, ADR-0226, ADR-0227, ADR-0230, ADR-0233, ADR-0236, ADR-0240 and
> ADR-0241 are relied upon as written.

> **Normative.** **ADR-0241 is relied upon in full and no pair is written on its line.** §10
> maps its two `SearchDisposition` members by name and takes no clause of it: its deadline, its
> `WebSearcher` argument, its accounting of an interrupted call and its closure of that
> enumeration at eighteen are all used as given, and this ADR widens, narrows and reopens none
> of them. Mapping a member into a second vocabulary is a stacked addition under ADR-0082 §1,
> not a change to the ADR that minted it, so ADR-0070 §1's test returns *no record owed*.

> **Normative.** **ADR-0193 §13's assignment is discharged and not superseded, and no pair is
> written on that ADR's line.** §13's rule is that the surfaces are decided by the ADRs that
> govern them rather than by an implementing lane, and this ADR is such an ADR: it decides the
> command-line surface in its own ratified text, leaves ADR-0177 §1's browser enumeration
> unwidened and defers the browser to a lane that widens it in its own text (§5), and states
> ADR-0199 §3's placement posture for what it produces. **That is ADR-0235 §9's own discharge
> read one act over**, and ADR-0235 records no supersession of §13 for it. A reader holding
> only ADR-0193 acts no differently, so ADR-0070 §1's test returns *no record owed*.

> **Normative.** **ADR-0238 §14's surface assignment is likewise discharged and not
> superseded.** That clause obliges *"the lane"* implementing ADR-0238 to implement no surface
> and reserves the question — and it stays true of that lane: batch #2178's lanes B1 and B2
> mint no trust record and ship no command. What this ADR supplies is the reserved decision, by
> the route §14's own last sentence anticipates. **§16's deferral of "The surfaces that offer
> §1's act" is *fired*, which is that entry's stated behaviour and not a change to it.** The
> one scope on which ADR-0238 *is* superseded is §1's refusal type and nothing else, and the
> header records that alone.

> **Normative.** **ADR-0235 §8's second and third clauses are relied upon and are not moved**,
> and this is stated because the header's scope is easy to read wider than it is. The listing
> remains the place the act is performed, it remains not a notification, and it remains barred
> from saying that the turn would have answered differently, that a reply was incomplete, that
> a search would have succeeded, or that anything is owed. §6 and §9 add a **statement of
> fact** about a lookup that did not happen and an act that would enable it; neither adds a
> claim about a counterfactual, and §9's bars are what keep them apart.

> **Normative.** **ADR-0228 §10's remaining clauses are relied upon and are the pattern this
> ADR follows**, so the one moved sentence is not read as loosening them: the carrier still
> travels inside `ai_assistant.orchestration` as data, adds no member to a Protocol, is never
> inferred at the render site, and reaches no step account — ADR-0170 §5a's closed vocabularies
> gain no member. **The two carriers coexist on one turn**, and a turn that both stopped while
> asking and did not service a search carries both facts, each rendered by its own fragment.
> Neither substitutes for, suppresses or is derived from the other.

> **Normative.** Additions this ADR makes that contradict no sentence an earlier ADR wrote are
> **stacked additions** under ADR-0082 §1 and are recorded here and nowhere else: §2's three
> engine members, its `UntrustableDestinationError`, its `SearchNotServiced` enumeration and
> its one `TurnOutcome` field; §5's three commands and the next-step line; and §11's
> `PROTOCOL_VERSION` move, which is ADR-0124 §9's own rule applied rather than changed.

> **Normative.** On **ADR-0231**, whose `Status` line already leads with `Partially superseded
> by` and already carries two pairs, this ADR's pair is **appended** on the same line under
> ADR-0070 §4's accumulation rule, and no existing pair is dropped or rewritten. On
> **ADR-0228**, whose line already leads with that token and carries one pair, the same. On
> **ADR-0235** and **ADR-0238**, whose lines read `Accepted`, the line takes the leading token
> and `Accepted` is dropped, as `docs/adr/template.md` requires. **No ratified sentence of any
> of the four is rewritten**, and no body text outside the header is touched.

> **Normative.** **These records are made in this ADR's own change, while it stands
> `Proposed`**, which is ADR-0082 §7's rule rather than an oversight: *"§1's condition is that
> the superseding ADR **exists**, not that it is ratified — the hazard §1 names is a `Status`
> line pointing at nothing, and an atomic pair makes that unreachable."* And the alternative
> would cost a round: ADR-0165 exempts a ratification flip only where it is one ADR file and
> one changed line, so moving four other files' `Status` lines in that commit would forfeit the
> exemption. No lane defers these records to the flip.

> **Normative.** **Three near misses are named, because each was a supersession an earlier
> draft of this ADR would have owed and each is avoided by a decision rather than by luck.**
> ADR-0170 §4's `reply_degraded` shape, by §6 declining to set it; ADR-0193 §1's exact store
> surface and ADR-0238 §1's five-member store surface, by §4's `bool` return declining to want
> a member `revoke` does not have; and the `SearchDisposition` closure ADR-0241 §8 now holds at
> eighteen, by §8 building a second vocabulary rather than adding to that one. A lane that reverses any of the three owes
> the record it avoids, and says so.

### 17. This ADR classified under ADR-0070 §1 and ADR-0082 §1

Each edit, with §1's test applied: would a reader holding only the earlier ADR now act
differently, or read one of its clauses more widely than it now holds?

**ADR-0231 §9's third clause — supersession.** A reader holding it builds a composing stage
that receives nothing on a turn whose search was refused, and asserts prompt byte-identity on
that turn. Both are now false for the class §6 names. The clause is not narrowed but reversed
within that class, and reversing a decision is supersession rather than amendment (ADR-0070
§1). Its three sibling clauses are untouched, so the form is partial.

**ADR-0235 §8's first clause — supersession.** A reader holding it refuses to put the message
in a reply, in terms and with the word *"nowhere else"*. §6 and §9 put a statement in the
reply. Same test, same answer, same partial form; §8's other two clauses are untouched, which
is why the scope names the first alone.

**ADR-0228 §10's first clause, second sentence — supersession.** A reader holding it asserts
that on every turn but its own the assembled prompt is byte-identical to today's. §6 makes
that false for a second class of turn. It is the narrowest of the four scopes — one sentence
of one clause — and it is recorded rather than argued away because a reader would otherwise
write a test that now fails for a reason the corpus does not explain.

**ADR-0238 §1's `record` refusal clause, in the refusal's type — supersession.** A reader
holding it builds `record` raising one class on three grounds. §2 gives one ground a subclass.
The base class still catches all three, so nothing a caller wrote stops working — but a lane
implementing ADR-0238 would not write the subclass, and a surface reading ADR-0238 alone could
not tell the already-chosen case from the others. That is *acting differently*, and it is the
same call ADR-0235 §4 made on ADR-0193 §1's *"one class rather than several"* limb.

**ADR-0193 §13, ADR-0238 §14, ADR-0238 §16 — no record owed.** Each reserves a decision to a
later ADR; this is that ADR; a reader holding either acts exactly as before. Discharging a
reservation is not amending it, and §16 argues the point in full because the contrary reading
is the natural one.

**ADR-0170, ADR-0177, ADR-0186, ADR-0193 §1, ADR-0231 §13 — no record owed.** Each is a near
miss §16 names, avoided by a decision. ADR-0197's precedent is the one that settles ADR-0170:
that ADR added a `TurnOutcome` field defaulting to `None` and recorded no supersession, and
ADR-0235 §4 did the same and recorded none either.

### 18. Marking, review and ratification

> **Normative.** This ADR is marked under ADR-0089: the block quotes above are the whole of
> what it obliges, and unmarked text is read to determine what a marked clause means and never
> supplies an obligation.

What binds is **one hundred and seventeen marked clauses**: §1's eight, §2's nine, §3's seven,
§4's eight, §5's nine, §6's five, §7's six, §8's eleven, §9's thirteen, §10's three, §11's
eight, §12's seven, §13's eight, §15's four, §16's ten, and this section's one. §14's deferrals,
§17's classification, and every argument, table caption and worked comparison in this
document are deliberately unmarked: they are deferral, attestation and argument, which
ADR-0089 §1 classifies as non-normative however load-bearing.

**Required reviews: adversarial *and* architecture.** This is a contract-surface change in
`CONTRIBUTING.md`'s sense — it decides three `AssistantEngine` members, a `core/types.py`
enumeration, a `TurnOutcome` field, two `core/errors.py` classes and a `PROTOCOL_VERSION`
move, and it moves clauses of four ratified ADRs — so it owes both lenses under ADR-0015 §1.
It is drafted, reviewed and revised as `Proposed`, its status flipped only once both required
reviews return clean on one tree, and the route is `CONTRIBUTING.md` → "Finishing an ADR PR".
Nothing implements against it until it has merged (ADR-0015 §5, golden rule 5).

**It landed beside a sibling it did not depend on.** ADR-0241 decided the search deadline in
the same batch and §10 states the seam. ADR-0241 merged first, this lane's base moved across
`docs/adr/**`, the round that move owed was spent rather than argued about (ADR-0027 §2,
ADR-0209), and §8's table names ADR-0241's two `SearchDisposition` members outright as a
result. Neither ADR ever read the other's text, and neither left a clause the other had to
complete.

## Consequences

- **The mechanism ADR-0238 built becomes reachable.** `app/composition.py`'s standing comment
  — *"until a surface offers the establishing act the store is empty, so every ruling is the
  one it was before"* — stops being true of destination trust once this ADR's lane lands, and
  milestone 31's journey becomes performable from a terminal by a person who has not read an
  ADR. That is the whole point of the decision and it is also its largest risk: a fact whose
  entire safety argument rests on *the user chose this* now has a control the user can reach,
  so §3's floor and §5's two-command rule are the load-bearing parts of this document, not §2.
- **A reply stops being silent about what it could not do.** The corpus's posture since
  ADR-0231 has been that a refused read is invisible to the reply and visible in a listing.
  That was right for a mechanism that never fired and is wrong for one that fires every turn,
  and the change is stated as a supersession of two clauses rather than as a reinterpretation
  of them.
- **Two carriers now reach the composing stage and a third would be too many.** ADR-0227 §3,
  ADR-0228 §10 and this ADR each supply the stage one fact it cannot infer. Each is cheap; the
  set is not, because every one of them is a prompt input that moves replies. §14's deferral of
  a per-servicing member is where the line is drawn, and an ADR adding a fourth carrier should
  argue against this sentence.
- **The command line grows by three and the browser by none.** A user on the browser can
  establish a recipient grant nowhere and destination trust nowhere, and now receives a
  `TurnOutcome` field it renders nothing for. That gap is named in §5 with the lane that
  closes it, and it is the same gap ADR-0235 §9 opened and named.
- **`SearchDisposition` and `SearchNotServiced` are two vocabularies over one event**, and
  they will drift if a later lane treats either as derivable from the other. §8's
  non-injectivity is deliberate and §11 keeps the second out of the audit, but the maintenance
  cost is real: a nineteenth disposition needs a mapping entry, and §15's totality arm is what
  makes forgetting one a test failure rather than a silent `UNAVAILABLE`.
- **`DestinationTrustStore.live` joins the unbounded reads #1551 asks about.** §4's listing
  has no `limit` for a good reason and no bound for the same reason the grant stores have
  none; a deployment that accumulates many trust records will find that out before #1551 is
  answered.
- **What would trigger revisiting this.** A measurement that users perform the grant act and
  not the trust act, which would say §5's next-step line is too weak and §14's per-row trust
  read is owed. A measurement that replies carrying `UNAVAILABLE` are the common case, which
  would say the situations behind it need splitting. And an ADR admitting a bounded audible
  channel, which reopens §5's withholding on its own terms.

## Alternatives considered

**A `--trust` flag on `assistant remember-recipients`.** One keystroke, one journey, and it is
refused by ADR-0238 §1's *"knowing it was a second question"* in terms. It also makes the two
records' independence undemonstrable at the surface: a user who wanted the grant and not the
trust would have to know that omitting a flag is an act.

**Accepting a destination the user types.** `assistant trust-destinations https://…` reads
better than an id, and it would put the construction of a `CanonicalDestination` in
`interfaces/` — business logic in an adapter (golden rule 3) — and let the user trust a set
that does not match the one `EgressBinding` will actually be bound to. The id is worse to type
and is the only form in which the user and the system are looking at the same value.

**Dropping §1's `planned_with_external_content` condition.** It costs a real case: a
destination whose only refused call was planned over external content cannot be trusted at
all, and the user's recourse is to ask a question that produces a clean call to it. That is
accepted, because trust is exactly what lets one call's results shape the next, and admitting
the act on a call an injected page shaped closes that loop from the wrong end.

**Deriving the reply's explanation from `SearchDisposition` alone.** Simplest, and wrong for
the reason §8 records: `RULING_CONFIRM` covers two situations with two different user acts.
A single-input mapping would send half of milestone 31's users to the wrong command, and no
test over the disposition alone would catch it.

**Putting the command name in the model's reply.** It reads as one sentence and it fails on
two channels the corpus already ships, and it makes a literal string a model's to paraphrase.
The split in §9 is uglier on a terminal and is the only form that is true everywhere.

**A bare `bool` carrier, as ADR-0228 §10 has.** Smallest change, and it makes the reply say
that something did not happen without saying which act is missing — which is the half of
#2168 the owner's amendment names. §7 records the departure and the clause it departs from.

**Writing `SearchNotServiced` to the audit beside `disposition`.** Tempting, since the
computation is already at the emission site. Refused: ADR-0238 §11 fixes what that event
carries, an operator reading two spellings of one event will read them as two events, and the
two vocabularies would drift with no test able to see it.
