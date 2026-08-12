# 139. A standing grant is read from the store, not from the sources the hub can offer

- Status: Proposed
- Date: 2026-08-12
- **Decides the grant-management surface** ADR-0133 §7 holds for leg 11 — how
  sources are presented, how a grant is amended, and what a user is shown about
  the grants they hold — and rules on the audit-of-read ADR-0097 §12 deferred and
  on the permission half of #441's release ladder. It **absorbs #629's residual**
  and closes it.
- **Adds one method to `AssistantEngine` — `standing_grants` — and one member to
  `SourceGrantStore`.** No new `core` type, no new error class, no new `Settings`
  figure, no change to `SourceGrants`, and no code ships with it. Golden rule 5
  and ADR-0015 §5 put a contract ADR in its own PR, merged before anything
  implements against it.
- **Required review set: adversarial *and* architecture.** The PR carrying it is
  prose only, and `ship.sh` gates the architecture lens on `core/protocols.py` or
  `core/types.py` changing — but the *decision* is `core/protocols.py` surface,
  which is the ground ADR-0093 through ADR-0102 each took the set for, and which
  `CONTRIBUTING.md` → "Stop when the required reviews are green" states directly.
- **Partially supersedes ADR-0102 §1**, and only its third limb. §9 states the
  extent clause by clause: the sentence "No other operation on any surface
  creates, revokes, or reports a `SourceGrant`" keeps its `creates` and `revokes`
  limbs whole and loses its `reports` limb. **ADR-0102's Status line carries the
  record under ADR-0070 §4 and ADR-0001, and it lands in this change** — the
  partial-supersession token plus the appended dated note ADR-0082 §2 puts it in,
  atomically with this ADR on ADR-0136 §7's and ADR-0138 §7's precedent, closing
  **#1016**. §8 carries the clause and the reason.
- **Amends no other ADR and supersedes none.** §9 applies ADR-0070 §1's test and
  ADR-0082 §1's record rule to the six further places where the opposite reading
  is available: ADR-0097 §2's two-act form, ADR-0097 §12's read deferral,
  ADR-0102 §3's `GrantableSource`, ADR-0102 §6's disclosure clause, ADR-0102 §14's
  liveness deferral, and ADR-0094 §10's ladder deferral.
- **Every claim below about the tree is stated as of `25ceecb7` on `origin/main`,
  read rather than remembered**, and every reference to a neighbouring ADR is to
  its text as merged at that commit rather than to its status on any later day.
- **Two documents that describe this ground are stale at that commit and are not
  edited here.** #629's body and `docs/roadmap.md` §11 both describe the grant
  model as unbuilt; ADR-0097, ADR-0102 and ADR-0133 are merged and implemented,
  and legs 9 and 10 verified grants against a live hub (#919, #978). The roadmap
  paragraph is corrected in a separate lane of batch #1009; this ADR reads the
  code rather than either document, and cites the roadmap only for its exit test.

## Context

### What is built, read rather than assumed

At `25ceecb7`, the whole of ADR-0097, ADR-0102 and ADR-0133 is on `main` and
wired:

- `core/protocols.py` carries `SourceGrants` (one member, `live`) and
  `SourceGrantStore` (`record`, `live`, `recent`, `export`, `clear`).
  `core/types.py` carries `GrantScope` with three members — `FACET`, `INGEST`,
  `NOTIFY` — `SourceGrant` with five fields, and `GrantableSource` with three.
- `permissions/grants.py` holds `SqliteSourceGrantStore`, and
  `app/composition.py` opens `grants.db` under the data directory and passes the
  one object twice: as a `SourceGrantStore` to `GrantOperations` and as a
  `SourceGrants` to `CalendarContextSource`, `IngestionStage` and the upcoming-event
  producer.
- `orchestration/grants.py`'s `GrantOperations` implements the four operations
  over that store and the identities the composition root built, and `Engine`
  delegates to it. `HubEngineClient` carries the four, and `interfaces/cli.py`
  exposes them as `sources`, `grant`, `revoke` and `grants`.
- The three gates exist and are the callers': `context/sources.py` for `FACET`,
  `orchestration/ingestion.py` for `INGEST`, `orchestration/upcoming.py` for
  `NOTIFY`, each a `live()` check with no `await` before the read and a re-check
  after it.

So the grant *model* is not what leg 11 is missing. What it is missing is the
surface a person manages grants through. ADR-0133 says so twice: §6's closing
paragraph — "What stays leg 11's is the grant-management **surface** — how sources
are presented, how a grant is amended, what a user is shown about their standing
grants — which #629 holds and which this member joins rather than reshapes" — and
§7's first bullet, which lists the same three questions among what that ADR does
not decide.

### The leg's own exit test names the gap

`docs/roadmap.md` §11's exit test reads: "the user can see **every source the
assistant reads**, grant and revoke each one, and a revoked source stops reaching
the model." The second and third clauses are met by ADR-0102's `grant` and
`revoke` and by ADR-0097 §5's gate. The first is not, and the reason is
structural rather than cosmetic.

### The hole: a live grant that no operation reports

`grantable_sources` enumerates **the readers the hub holds** (ADR-0102 §7), one
entry per declared identity, each carrying that source's live grant. It is
therefore an answer keyed on the composition root, not on the store. A grant
whose reader the hub no longer builds — an operator unset `calendar_reader_path`,
or a reader was removed from the tree — is not in that enumeration at all.

`recent_grants` returns records, and ADR-0102 §3 is normative that liveness may
not be derived from it: "No client may derive a grant's liveness from
`recent_grants`, and no surface may present a record `recent_grants` returned as
live or as withdrawn on its own." The reason is concrete rather than tidy —
ADR-0097 §4 permits a revocation timestamped before the grant it revokes, and
`recent` orders by `decided_at`, so a clock correction can put a revoking record
outside a page that contains its grant.

`SourceGrants.live` is per source and takes a source name, so it cannot be swept
without already knowing the names to sweep. `SourceGrantStore.export` returns
every record ever written and has no caller anywhere in `src/`; ADR-0102 §14
keeps it in ADR-0101 §7's export lane.

**So there is a state in which a user holds a live grant and no operation on any
surface reports it as live.** It is revocable — ADR-0102 §4 rules that `revoke`
applies no admission check precisely so that a configuration edit can never make
a grant unrevokable — but the user must already know the source's name to
withdraw it, and nothing tells them. ADR-0102 §14 saw this and deferred it, with
a firing condition that names this lane: "Fires with ADR-0093 §11's source
registry, **or earlier with the first deployment that removes a reader while a
grant stands and needs to say so**." A surface whose subject is what the user has
granted is the thing that needs to say so.

### Amendment is two acts, and no surface says which of them landed

ADR-0097 §2 rules that "changing a grant's scope is a revocation followed by a
new grant, and both records are kept", and ADR-0102 §1 refuses a compound
operation for the same reason. That is the right record shape and this ADR does
not reopen it.

What nothing decides is the **surface** over it. An amendment is two round trips
through the hub, and the second can fail on its own: an oversized frame, a hub
restart between them, a `GrantError` from the store, an
`UngrantableSourceError` because the reader stopped being held between the calls.
The user asked to narrow a scope and is left with **no grant at all** — and the
natural thing for a client to report is that the amendment failed, which reads as
"nothing changed". Something did change: the source stopped being granted, and
under ADR-0097 §5 it stopped being read.

`interfaces/cli.py` today offers no amendment at all; a user amends by running
`revoke` and then `grant` themselves, which at least leaves them holding both
outcomes. The moment a surface offers amendment as one act, the intermediate
state becomes something a person can land in without seeing it.

### The read record: what ADR-0097 §12 deferred, and what has changed under it

ADR-0097 §12 deferred "an audit record of each *read*, which #629 asks for
alongside the grant", with this reasoning and this firing condition:

> Today the record of what a source said is the beliefs it produced, each
> carrying `reported_by` and `reported_at`, and a per-read row would be an
> unbounded Tier 1 store with no reader. Fires when something needs to know about
> a read that produced no belief.

The premise was already only two-thirds true when it was written and is now only
one-third true. A `FACET` read produces a transient facet that is never stored
(ADR-0097 §2, ADR-0008 §4) — `context/sources.py` discards a reading whose grant
has gone and records nothing anywhere. A `NOTIFY` read (ADR-0133 §1) concludes a
`NotificationCandidate` **or concludes nothing**, and concluding nothing is the
ordinary outcome. Only `INGEST` leaves the residue the deferral rests on, and
only when `MemoryPolicy` accepts what was proposed.

So two of the three uses a grant may name now leave **no durable trace of a read
at all, by design**, and the third leaves one conditionally. That is the deferral's
own firing condition met, arriving from a direction it did not name.

It also matters that ADR-0004 §7's charter has two halves and only one is built
for this subject: "Access to Tier 0/1 data and every side-effecting tool call is
gated by the `permissions/` layer and **recorded in an audit trail**." ADR-0097
built the gate. ADR-0097 §4's append-only grant store records the *authorisation*,
not the *access*, and saying otherwise would be reading the sentence past its
grammar. §6 below is where that is stated rather than glossed.

### An honest statement of what this ADR is not allowed to settle

- **The grant record's shape, its store, its liveness rule, and revocation's
  effect.** ADR-0097 decided all four and this ADR builds a surface over them.
- **A source registry, an instance-distinguishing identity, and what a live grant
  does when its source's backing location changes.** ADR-0093 §11 and ADR-0097
  §9a's named precondition own it, unchanged.
- **Content-level scope, lapsing grants, per-belief attribution, who granted, and
  everything else ADR-0097 §12 and ADR-0102 §14 defer.** Unchanged and not
  re-listed.
- **The export and erasure surface.** ADR-0101 §7 records that ADR-0004 §6's
  export right has no user surface at all and ADR-0102 §14 keeps the grant
  store's `export` and `clear` in that lane. §10 leaves them there.
- **Voice, ambient capture, and #441's `VISION.md` amendment.** §7 rules on the
  permission axis of #441's trigger ladder and on nothing else it holds.
- **CLI spellings.** ADR-0073 §1's form governs: what a command is called is the
  client lane's, and §3 below binds properties rather than words.

## Decision

We will make the surface answer two questions from two different places — what
may be granted, from the readers the hub holds; what **is** granted, from the
store — add the one operation the second question needs, rule that amendment
stays two acts whose intermediate state the surface must state, fire ADR-0097
§12's read deferral into a lane of its own with binding conditions, and bind the
capture lane that would climb #441's trigger ladder.

### 1. The surface answers two questions, and neither is derivable from the other

> **Normative.** The grant-management surface answers two questions and keeps them
> apart. *What may I grant?* is answered from the readers the hub holds, and
> `grantable_sources` is its answer (ADR-0102 §3). *What do I currently
> authorise?* is answered from the grant store, and `standing_grants` (§2) is its
> answer. No implementation may derive either answer from the other, and no
> surface may present one as the other.

> **Normative.** The two answers may disagree, and a disagreement is a legitimate
> state rather than a fault. A source may be grantable and ungranted, granted and
> not currently held by the hub, or both grantable and granted. No implementation
> may reconcile them, suppress an entry of one because it is absent from the
> other, or refuse an answer because they differ.

**The split is the fix for the hole and it is also what the corpus has been
saying all along.** ADR-0093 §7 rules that configuration is not a grant and that
no surface may present it as one; ADR-0097's Consequences restate it as two acts —
"Configuration says *where* and *how often*; the grant says *whether* and *for
what*." A surface that reads both answers off the same list is exactly the
collapse those clauses forbid, arriving through a data structure instead of
through a field. `grantable_sources` is keyed on configuration and carries a
grant; that is right for the granting flow and wrong as the standing view, and
the failure is silent in one direction only — a grant on an unheld source
disappears, while a source with no grant is merely listed as ungranted.

**Derivation in the other direction is unsound for ADR-0102 §3's own reason.** A
client could try to answer "what do I authorise" by walking `recent_grants` and
applying the `revokes` relation itself. ADR-0102 §3 forbids it, and the concrete
failure is the one it names: a revocation timestamped before its grant sorts
below it, falls outside the page, and the client reports a withdrawn grant as
live — on the deployment where a clock moved, which is the failure that never
shows up in a test.

### 2. `standing_grants`: one engine method, answered from the store

> **Normative.** `AssistantEngine` gains **one** method,
> `async standing_grants(self) -> tuple[SourceGrant, ...]`, returning **every**
> grant that is live at the moment the response is computed, whatever the hub
> holds. It takes no argument. It declares `GrantError` and `OversizedValueError`
> and no other failure.

> **Normative.** The result is computed from **one** read of the store, so it is a
> snapshot: no source appears in it twice, none is missing because another was
> being written, and the set is internally consistent. It is not a claim that
> stays true after it is computed, and no client may present it as one.

> **Normative.** `standing_grants` returns the **complete** live set or it fails.
> It is not paged, admits no `limit` and no `offset`, and no implementation may
> truncate, sample or elide its result. Where the result does not fit the
> configured frame it raises `OversizedValueError` and reports nothing.

> **Normative.** `standing_grants`' liveness is computed from the store's
> `revokes` relation alone (ADR-0097 §4). No implementation may derive it from
> `decided_at`, from `recent`'s ordering, or from which readers the hub holds.

> **Normative.** The order in which `standing_grants` returns its records carries
> no meaning. No client may read a precedence, a recency claim or a liveness claim
> off a record's position, and an implementation's chosen order is a display
> convention rather than a contract clause.

**The snapshot clause borrows ADR-0102 §3's wording rather than inventing one, and
an earlier draft overclaimed.** That section defines `GrantableSource.live` as
"the grant covering that source at the moment the response was computed", and the
same bound is the honest one here: a `grant` recorded after the read and before
the client renders is outside the set, as it is outside every other read in this
system. What the clause does buy is the property a *set* can have and a scalar
cannot — that the answer is one read rather than a walk that another write can
interleave with, so a source cannot be doubled or dropped by the timing of a
concurrent record.

**A second writer is not the case this guards, and testing for one would test a
state the system refuses.** ADR-0083 ruling 4 gives the hub exclusive ownership of
every database under the data directory, one process per directory behind an
instance lock, and ADR-0102 §12 already recorded that the grant store "lives inside
the directory the instance lock already covers, is opened by the same process". So
the interleaving this clause forecloses is the one that is actually reachable —
another coroutine on the hub's own event loop, `record`ing between two reads of a
multi-read implementation — and it is foreclosed by requiring one read rather than
by a lock.

**Not paged, and the refusal is the safe direction.** A paged answer to "what do
I authorise" can omit an authorisation while reading as complete, which is the
same class of failure ADR-0102 §3 refused when it forbade deriving liveness from
a page. A refusal cannot be mistaken for an empty set: `OversizedValueError` is a
declared failure a client renders as one, and the operator's remedy is
`hub_max_frame_bytes`, exactly as ADR-0102 §10 rules for `grantable_sources`. The
directions are also the same in the way that matters — a frame too small to list
what you authorise still lets you withdraw what you know about, because `revoke`'s
request and result are two small values (ADR-0102 §10).

**The set is bounded by one live grant per source (ADR-0097 §4) and by the number
of distinct identities ever granted, and this ADR bounds neither by contract.**
Today that is one. It grows with the identities a deployment has granted across
its life rather than with grant churn, which is the difference between this method
and `recent_grants` and the reason `recent_grants` keeps its `limit`. ADR-0102
§14's deferral of a guarantee against unbounded identifiers is unchanged and
reaches this method too: `Identifier` and `DurableIdentifier` carry no maximum
length, so a sufficiently long identity or minted id exceeds a small configured
frame here as it does there.

> **Normative.** `SourceGrantStore` gains **one** member,
> `async standing(self) -> list[SourceGrant]`, returning every live grant in the
> store, computed from the `revokes` relation. It takes no argument, is not paged,
> and returns detached snapshots as every other query on that seam does
> (ADR-0097 §4). It declares `GrantError` and no other failure.

> **Normative.** `SourceGrants` is **unchanged**. The enumeration is not added to
> the query seam, and no site that drives a reader may name it.

> **Normative.** A store holding **two live grants for one source** answers the
> enumeration with `GrantError` and answers nothing else. It does not return both,
> does not choose between them, and does not return the sources it could answer
> for. `standing_grants` propagates that `GrantError` rather than converting it.

**The corruption is not hypothetical and the existing store already refuses it
one query over.** ADR-0097 §4 guarantees at most one live grant per source and
`record`'s atomic check is what keeps it true, so two can only arrive by a
corrupted or hand-edited file — and `SqliteSourceGrantStore.live` already raises
`GrantError` on exactly that, reasoning in its own docstring that "picking one of
them would answer the gate from a store that cannot say what the user granted".
An enumeration written as the same anti-join with its source predicate dropped
would silently return both, so the invariant that holds per source has to be
restated over the store-wide query or it is lost at precisely the point the query
stops naming a source.

**Refusing the whole call rather than the affected source is §2's completeness
clause applied to itself.** Two live grants for one source make that source's
authorisation unstatable — the user would be shown two standing grants where
revoking one leaves the other live, and a later `grant` would be refused for a
source the surface said was ungranted. Returning the rest with the bad source
omitted is a set that reads as complete and is not, which is the failure the
no-paging clause exists to prevent; a declared `GrantError` cannot be mistaken for
an empty set. This is also the direction ADR-0097 §5a fixes for an unanswerable
grant check — fail closed, and never proceed on the better of two answers.

**It is stated rather than left to the implementation, because the wrong version
passes every test a lane would otherwise write.** Every record a conformance suite
can create goes through `record`, which refuses the second live grant, so the
corrupt state is unreachable from the suite unless the suite is told to construct
it — the same reason ADR-0097 §10 required its fakes to be scriptable into states
their own writers refuse. §8 carries the obligation.

**The store member is required rather than convenient, and the alternative is a
surface that lies about its cost.** `SourceGrants.live` is keyed on a source name,
so an engine-side answer would have to come from `export()`, whose cost grows with
the store's whole history rather than with the number of live grants — which is
the objection ADR-0102 §10 raised against an engine-side `offset`
("over-fetch-and-slice — a paging surface that lies about its cost"). The query is
the store's existing live anti-join with its source predicate dropped, over rows
the shipped schema already holds and already indexes — which is why §8 rules that
no new database and no schema version bump ride with it.

**Leaving `SourceGrants` alone is ADR-0097 §3's capability split held rather than
restated.** That section removed `record` from the driver's type so that "a
scheduler job that can mint its own authorisation" is a type error rather than a
promise. An enumeration is not a minting capability, but it is not a driver's
business either: a driver asks about the one source it is about to read, and a
driver that could enumerate the store is one that could log or leak the set. The
seam stays at one member, which is also what keeps §3's "one implementation
satisfies both" cheap.

**Why one more method rather than widening `grantable_sources`.** Adding the
ungranted-but-standing case to that operation would make its name false — a source
no reader declares is precisely one that `grant` refuses under ADR-0102 §4 — and
would require the `grantable: bool` field ADR-0102 §3 refused, reopening a
ratified type to carry a state the enumeration's own name denies. ADR-0102 §1's
own reasoning is the precedent: `grantable_sources` and `recent_grants` were kept
apart because they "answer different questions". This is a third question, and it
is kept apart for the same reason.

### 3. What a client presents, and what it may never present

> **Normative.** A surface presenting standing grants presents the set
> `standing_grants` returned, whole. It may not omit a record because no held
> reader declares its source, may not merge the set into an enumeration of
> grantable sources, and may not present a standing grant as a source the user
> may grant.

> **Normative.** Wherever a surface offers, enumerates or explains the uses a
> user may choose among, it carries **every** member of `GrantScope`, named in
> words. No client may offer, enumerate or explain a proper subset of the members
> its own type admits.

> **Normative.** Wherever a surface renders an existing grant, it renders exactly
> the uses that grant names. It may not add a use the grant does not name, may not
> omit one it does, and may not present a partial scope as incomplete, provisional
> or in need of the members it leaves out.

> **Normative.** No surface presents a source's configuration state as part of a
> grant, and no surface presents a grant as a statement about whether a source is
> being read. What a grant says is what the user authorised; whether a read
> happened is not a question this surface answers (§6).

> **Normative.** No client presents a record from `recent_grants` as live or as
> withdrawn on its own (ADR-0102 §3), and no client presents `recent_grants` as
> the answer to what the user currently authorises.

**The second clause is ADR-0133 §6's CLI obligation stated over the property it
was protecting.** That section required `interfaces/cli.py`'s `--scope` help to
name all three uses, reasoning that "a help string enumerating two of three uses
is a surface disagreeing with the vocabulary — which is the failure ADR-0097 §8
names when it forbids anything deciding what the user permitted on their behalf."
The reasoning is not about Typer. Stated over the surface it binds the next client
too — a spoke, a graphical one — where the type-level accident that makes the CLI
correct today does not exist.

**The third clause is what keeps the second from reaching a rendering, and the two
are separated because a single clause covering both is false in one direction.**
An earlier draft stated the vocabulary rule unqualified — "no client may offer,
enumerate or explain a proper subset of the members its own type admits" — and
adversarial review showed it forbade the truthful display of a `FACET`-only grant:
rendering `FACET` alone *is* enumerating a proper subset, and rendering all three
would say the user granted uses they did not. The choice context wants the whole
vocabulary because a user cannot choose what they are not shown; the rendering
context wants exactly the grant, because ADR-0097 §2's "a use a grant does not
name is not authorised by it" has a display counterpart and this is it. Two
contexts, two obligations, and ADR-0089 §2's "a clause states one obligation" is
the form that made the collision visible.

**The trailing half of the third clause is aimed at the sympathetic version of the
same error.** A view that renders a `FACET`-only grant as `FACET` and then greys
out `INGEST` and `NOTIFY` beside it is presenting the user's decision as a
half-filled form — which is the vocabulary rule leaking out of the choice context
by way of a layout, and is a nudge toward a wider grant on a surface whose whole
subject is what the user actually decided.

**The fourth clause is where a management surface is most likely to go wrong,
because the sentence a person writes is a true sentence about the wrong axis.**
"Your calendar is not being read" is what a user wants to hear and what a client
can nearly compute: the source is absent from `grantable_sources`, so no reader is
configured, so nothing is reading. It is still forbidden, for ADR-0096 §4's reason
one surface over — a field that reports enablement is a conversation about
configuration conducted where the user is deciding about consent, and the two are
the two acts ADR-0093 §7 exists to keep apart. A client that wants to say
something true about configuration calls the operation whose subject is
configuration and says it there.

**Nothing here is a spelling.** ADR-0073 §1's form governs the client lane's
words; these clauses bind what a presentation may assert, which is the half a
later client can get wrong without touching the CLI.

### 4. Amending a grant is two acts, and the surface says which of them landed

> **Normative.** Amending a grant is ADR-0097 §2's two acts — revoke, then grant —
> in that order, recorded as two records. No operation on any surface performs
> both, and no surface presents an amendment as atomic or as leaving the source
> continuously granted.

> **Normative.** A surface offering amendment as one user-facing act reports the
> outcome of **each** act, as one of exactly three: it **landed**, it is **known
> not** to have landed, or its outcome is **not known**. An outcome that is not
> known — the call was cancelled, or its response was lost after the hub may
> already have committed it — is reported as not known, and never as either of the
> other two. An amendment that did not complete is never reported as merely
> failed.

> **Normative.** No surface infers the **source's current grant state** from
> either act's outcome. `standing_grants` is what states it (§2), and a surface
> that has not read it says the source's state is unread rather than asserting
> one. In particular a refused `grant` is not a statement that the source is
> ungranted, and a landed revocation is not one either.

> **Normative.** Where the revocation's outcome is **not known**, the surface does
> not send the grant. It reports the revocation as not known, leaves the amendment
> incomplete, and does not infer the source's state from that unresolved act. A
> surface still free to call resolves the state by re-reading, rather than by
> sending a second act it could not interpret the outcome of; a surface being
> cancelled says the state is unread, and the user's next call reads it.

> **Normative.** Where an outcome is not known **because the amendment was
> cancelled**, the surface reports it as not known and the cancellation still
> propagates. A cancelled surface starts no new call in order to report: it reports
> the act as not known, says the source's state is unread, and lets the
> `CancelledError` leave. ADR-0060's rule that external cancellation is re-raised is
> neither relaxed nor satisfied by the report, and no surface may swallow a
> cancellation in order to make one.

> **Normative.** A surface offering amendment takes the user's decision about the
> new scope **before** it sends the revocation, and sends the revocation only for
> a source the user has decided a new scope for. No surface revokes in order to
> ask.

**The two-record form is ADR-0097 §2's and is not reopened.** Its argument is that
a narrowing applied in place "is a rewrite of a record the user made, in a store
whose entire value is that it says what the user actually decided", and that the
two-act form is legible at a glance. ADR-0102 §1 refused the compound operation on
the same ground and added a second: `revoke` cannot be `grant` with an empty
scope, because ADR-0097 §2 refuses an empty scope at construction. Both stand.

**What is decided here is the gap between the two acts, which the record shape
does not reach.** ADR-0097 §2 named the cost — "a moment in which nothing is
granted, in which a scheduler tick would be refused under §5" — and judged it a
log line on a single-user machine. That judgement was about the *hub's* behaviour
during a successful amendment and it holds. The case it did not reach is the
amendment that stops halfway, and the difference is that the momentary state
becomes the resting state without anyone deciding it should.

**"Not merely failed" is the whole of the second clause, and the wrong report is
the one an implementer writes.** A client that wraps two calls in one command has
one natural failure path: catch, report the exception, exit non-zero. The user
reads that as the amendment not having happened, goes away, and their calendar
stops being read — silently, because ADR-0097 §5's refusal is a log line and its
facet path is an absence indistinguishable from every other absence (ADR-0096 §4).
The state is recoverable in one command; being told about it is what makes it
recoverable.

**Three outcomes rather than two, because a mutating call over the socket has a
third and the corpus already knows it.** A `grant` can be committed by the hub and
lose its response — ADR-0085 §8e's residual, which the `AssistantEngine` docstring
states in its own words ("On a mutating call the result is measured after the work
has committed … a wire client meets the same situation one frame further out. The
effect stands and is readable through the surface's own reads"), tracked as #570 —
and ADR-0060 makes a cancelled write's effect indeterminate for the same reason.
A two-outcome contract forces a client in that state to assert one of two things
it does not know, so the third outcome is the honest shape rather than a
concession. It reaches the **revocation** as well as the grant, which is the fourth
clause: the first act is a mutating call over the same socket and has no better
guarantee than the second.

**The third clause is the sharper of the two, and an earlier draft got it
wrong.** That draft said a grant known not to have landed means the source is
ungranted. It does not: ADR-0102 §5 rules that two clients can be connected at
once and that the store, not the caller's lookup, is the arbiter — so a `grant`
refused with `InvalidGrantError` is refused precisely *because another client's
grant is live*, and "the source is now ungranted" is then false in the one case
that produced it. ADR-0102 §5's own remedy for the mirror case is the one taken
here — "the client re-reads … and sees the source is no longer granted, which is
what it wanted" — generalised into a rule: an act's outcome is a fact about that
act, and the source's state is a fact about the store, and one is never read off
the other. That is §1's split arriving in the flow.

**Which is the second consumer `standing_grants` earns rather than the one it was
designed for.** Every ambiguity in this section is resolvable by reading, and the
read that resolves it is the one §2 adds: a client that lost a response, or was
refused by a race, asks what the user currently authorises and is told, from the
store, whatever the hub actually did. That is also why the clauses name a re-read
rather than a retry — a retried `grant` against a hub that already committed one
is refused with `InvalidGrantError` (ADR-0097 §4's one-live-grant rule), which
reads to a user as a failure and is a success.

**The fourth clause stops rather than proceeds, and the reason is that proceeding
buys an answer nobody can read.** A client whose revocation is unresolved could
send the grant anyway and reason backwards from the result — refused means the
revocation did not land, accepted means it did. The inference is exactly the one
the third clause forbids, and for the same reason: a refusal is equally consistent
with another client having granted in between. One read settles it; a second write
does not.

**And it stops short of mandating the read, because on the cancelled branch a
mandated read is a call the surface may not make.** Cancellation is one of the two
routes to an unknown outcome the second clause names, so an unconditional "resolves
the state by re-reading" reaches a surface that is being cancelled — and ADR-0060
permits deferring a cancellation only while a method "makes its resources safe",
which a read performed to present a state is not. Such a clause would oblige a
cancelled surface either to breach ADR-0060 or to breach this section, which is no
obligation at all. The escape was already written into the third clause — a surface
that has not read says the state is **unread** — and the fourth clause now takes it
rather than restating a mandate the third clause had already made unnecessary.
Nothing is lost on the branch the mandate was written for: a surface whose
revocation was lost rather than cancelled is free to call, and reads. What is
invariant across both branches is the prohibition, not the read — the state is
never inferred from the unresolved act, and where this surface cannot read it, the
user's next call can.

**The fifth clause is what keeps the cancellation limb from being unreachable in
practice, and the hazard is a language detail rather than a design one.**
`CancelledError` is a `BaseException`, so the natural `except Exception` around
two calls does not see it: a client written that way exits without reporting
anything, and the one clause naming cancellation as a route to an unknown outcome
never runs. The other repair — catching it and carrying on to print — is worse,
because ADR-0060 requires external cancellation to propagate and a swallowed one
leaves a task the caller believes it cancelled. So both halves are stated
together, and the client lane owes a test for each act.

**Its middle sentence is what makes the clause answerable on its own, and it is
there because the report is the one thing a cancelled surface is still asked to
do.** Asking for a report invites the third repair — reach for the state before
reporting it — which is the same breach by a kinder route, and under ADR-0089 §3 a
clause that leaves it out obliges nothing against it. So the clause says what the
cancelled surface reports (the act, as not known), what it says about the source
(unread, which is the third clause's own vocabulary), and what it does not do
(start a call), and then lets the `CancelledError` leave. That is the complete
behaviour of the cancelled path in one clause, which is what a client written
against it needs and what §8's test asserts.

**The sixth clause removes the case that has no good report.** A surface that
revoked first and then asked the user what to grant would put the interactive part
of the flow *inside* the ungranted window — so a user who hesitates, or closes the
terminal, or is asked something they want to think about, has withdrawn their
grant by starting to think. Collecting the decision first does not close the
window, which the first clause says is not closable; it keeps the window
mechanical, bounded by two calls rather than by a person's attention.

### 5. The disclosure rides the grant act, not the flow around it

> **Normative.** ADR-0102 §6's disclosure obligation applies to **every** `grant`,
> including the granting half of an amendment: a client renders the source's
> `location` and takes an explicit act from the user before it sends `grant`, and
> a client that cannot show the user the location does not send `grant`.

> **Normative.** No client may skip the disclosure on the ground that the scope
> being granted is narrower than the scope being replaced, that the source was
> granted a moment earlier, or that the user has granted this source before.

**The obligation is ADR-0102 §6's read as written, and the marking is here because
an amendment is where it would be read as not applying.** §6's clause is about
`grant`, and the granting half of an amendment is a `grant` — same operation, same
record, same store. What makes the reminder worth a clause is that an amendment
*feels* like a modification of something the user already consented to, and a
client author reasoning that way skips the one step §6 exists for.

**The uniform rule is also the only one that needs no comparison of scopes.** A
client branching on "is this a narrowing" computes a relation over `GrantScope`
members, and ADR-0133 §2 is normative that no implementation may "infer one member
from another, **rank** them, or treat any of them as a superset of another", and
that the declaration order `SourceGrant.scope` normalises to "is a serialisation
convention and is not a rank". A narrowing test over two scopes is not itself a
ranking of members, so this is not that clause being stretched — it is that the
branch buys nothing except a place for that mistake to be made, and skipping the
disclosure is what it buys it for.

### 6. The read record is owed, is not this surface's, and here is what its lane owes

> **Normative.** ADR-0097 §12's deferral of an audit record of each read is
> **fired**: two of `GrantScope`'s three uses leave no durable trace of a read by
> design, so the beliefs an `INGEST` read produced are no longer the record of
> what a granted source was read for. A lane deciding that record is owed.

> **Normative.** This ADR does not decide it, and the grant-management surface
> does not report reads. No operation added here returns a read, a read count or a
> last-read instant, and no client presents one beside a standing grant.

> **Normative.** ADR-0004 §7's requirement that access to Tier 0/1 data be
> recorded in an audit trail is **not** discharged for source access by ADR-0097
> §4's grant store. That store records the authorisation; the access is
> unrecorded, and no surface may present the grant history as a record of reads.

> **Normative.** An ADR deciding the read record carries no source content, no
> entry, no path and no configured location on any record it defines (ADR-0004 §5,
> ADR-0093 §8).

> **Normative.** An ADR deciding the read record states a bound on the record's
> growth that is refused at load, and may not discharge this by appending without
> one. ADR-0097 §12's refusal was of "an unbounded Tier 1 store", and that
> objection is not answered by the deferral firing.

> **Normative.** An ADR deciding the read record states whether a read **refused**
> for want of a grant is recorded, and why. It may not settle that question by
> silence.

> **Normative.** No read record is ever consulted to decide whether a source is
> granted, and no implementation may derive liveness, scope or grant history from
> one.

**Firing it and not building it is a scoping answer, and the reason is that the
record is a store rather than a surface.** ADR-0097 §4 already ruled out the one
store that exists: `PermissionDecision.tool` is a required `ToolDefinition`, a
read has no declaration, and synthesising one would put "a fabricated record into
the one store whose entire premise is that its records are not fabricated". So the
record needs a new Protocol, which golden rule 5 and `CONTRIBUTING.md` →
"Adding a Protocol" put in its own ADR with its own triad. That is a different
subject from the surface this ADR decides, and one lane delivers one change.

**The second clause is the substantive half, not a scheduling note.** Reporting
reads on the management surface is the tempting fold, and it is the wrong subject:
the surface's question is *what do I authorise*, and "your calendar was read 412
times this week" answers *what has been happening*. Mixing them is §3's third
clause in the other direction — an activity claim standing where an authorisation
claim belongs — and it would also make the read record's consumer this surface,
which is how an unbounded store gets built to fill a column.

**The third clause is stated because the comfortable reading is available and is
wrong.** ADR-0097 §4 says "This answers 'are granting and revoking audited' by
construction rather than by adding a log", and ADR-0102 §11 restates it. Both are
about granting and revoking. ADR-0004 §7's sentence is about *access*, and its
record half is unbuilt for sources. Recording that plainly is what stops the next
reader concluding the charter is discharged because a neighbouring sentence was.

**The bound clause is where the first draft of a read record will go wrong.** A
calendar read on a five-minute interval is on the order of a hundred thousand rows
a year, for a deployment with one source; the honest shapes are a retention figure
named and refused at load in ADR-0093 §5's discipline, or a record that is not
per-read at all. Which of them is that lane's to choose; that it must choose one
is decided here, because "append and see" is the default an implementation reaches
without deciding anything.

**The refusal clause exists because the refusal is the security-relevant event and
today it is only a log line.** ADR-0097 §8 requires a legible operator log record
naming the source and the use refused, and ADR-0097 §5 notes that a
revoked-but-configured source produces one every interval. A log is not durable
state and is not exportable, so "was this source read after I revoked it" has no
answer today. That is a question the read lane may answer or may decline; what it
may not do is not notice it.

**Filed as #1017 with this ADR**, so the fired deferral is tracked as a lane
rather than as a paragraph, with the clauses above carried into it by reference
rather than by paraphrase.

### 7. #441's trigger ladder: the rungs are permission questions, and the model expresses exactly the first

> **Normative.** The grant model expresses exactly one rung of #441's trigger
> ladder: an explicit user act, per source, per use, recorded before the read
> (ADR-0097 §1). It expresses no consent per act, no assistant-initiated proposal
> to grant, and no standing authorisation for a trigger the user did not choose.

> **Normative.** No lane may implement a rung above the first by treating a
> standing source grant as covering it. A grant recorded before a trigger existed
> authorises the uses it names for the source it names, and nothing about what
> caused a read.

> **Normative.** A lane introducing a producer whose reads are caused by anything
> other than an explicit user act or a configured schedule owes, in the same
> change, the rule for how the user authorises that cause — and may not discharge
> it with the source-level grant this surface manages. This is a named precondition
> in ADR-0097 §9a's form, on the lane ADR-0094 §10 defers the ladder to.

> **Normative.** Nothing here decides what may cause a release at the edge
> (ADR-0094 §3), which rungs exist, or `VISION.md`'s sensor-spectrum amendment.
> #441 stays open for those.

**What is folded, and what ADR-0094 §10 actually said.** Its ladder bullet reads
"**What may cause a release** (§3) — #441's trigger ladder … Fires with the first
capture producer, and it is probably one decision with the grant model below
rather than two", and its grant bullet adds that the grant model "should be taken
knowing that the trigger ladder's rungs are permission questions and that a model
sized for one static file will not carry a microphone and a bystander". Two things
follow and they point opposite ways. The ladder's own firing condition is a
capture producer, and there is none — no spoke, no capture, no voice (#879 parks
it) — so deciding which rungs exist here would be deciding a lane with no producer
in hand, which is ADR-0073 §4's "with a producer in hand" and ADR-0045 §1's
surface-with-no-consumer refusal. But the *permission* half is decidable now,
because the grant model exists and the question is what it does and does not
express. That half is what the clauses above decide, and it is the honest reading
of "probably one decision": the fold is real, it runs from the grant model to the
ladder lane as a constraint, and it does not require this ADR to invent a ladder.

**The second clause is the one that will be reached for.** A capture lane holding
a store full of live grants and a new trigger has the same temptation ADR-0133 §3
named and refused for a new *use*: "A lane holding a store full of `(FACET,
INGEST)` grants and a new member could reasonably think it was being helpful by
treating an existing `INGEST` as covering the new use." A new *cause* is the same
move on the other axis, and ADR-0097 §2's surviving sentence — "a use a grant does
not name is not authorised by it" — is about uses and does not by itself decide
causes. Stating it is what keeps the ladder from being climbed by implication.

**The model's limit is named rather than repaired.** A grant is per source and
binary; #441's rungs 2 through 4 are per *moment* — "capture that" is consent to
one recording, and a salience classifier proposing a capture is the assistant
asking. Neither is expressible as a `SourceGrant`, and neither should be forced
into one: ADR-0097 §12 already defers content-level scope and a lapsing grant, and
a per-act consent is a third shape again. Which of them a ladder needs is that
lane's to decide with its producer in hand.

### 8. The contract surface owed, and what the implementing lanes owe

**New surface in `core` — a breaking change (golden rule 5):**

- **`core/protocols.py`** gains **one** method on `AssistantEngine` and **one**
  member on `SourceGrantStore`. **Every annotation is spelled out and the
  spelling is ratified, not the lane's**, in ADR-0085 §3's and ADR-0102 §2's
  form. The signatures below restate §2's two clauses and add nothing to them:

  ```python
  class AssistantEngine(Protocol):
      async def standing_grants(self) -> tuple[SourceGrant, ...]: ...


  class SourceGrantStore(Protocol):
      async def standing(self) -> list[SourceGrant]: ...
  ```

  Docstrings are omitted here and are not optional in the Protocols, exactly as
  ADR-0085 §3 and ADR-0102 §2 state for their own blocks. The store member's
  return shape follows its neighbours on that seam (`recent` and `export` return
  lists); the engine method's follows its neighbours on the promoted surface
  (`recent_grants` returns a tuple). `standing` is the one-word form its seam
  uses throughout — `record`, `live`, `recent`, `export`, `clear` — and collides
  with no member of it; the engine's `standing_grants` carries the noun because
  the promoted surface is flat and names the subject, as `recent_grants` does
  beside it.

  **The member had no ratified name anywhere, and that is the defect rather than
  the illustrative label.** An earlier draft left both spellings to the
  implementing lane on ADR-0073 §7's and ADR-0102 §2's authority; architecture
  review found it on round 1 of that lens, and neither citation carries it.
  ADR-0073 §7 leaves its names as "*shape*, not as spelling" for the reason it
  gives in the same sentence — "the seam is the concrete `orchestration` façade,
  which is **not** a contract surface" — which is the one thing that does not hold
  here. ADR-0102 §2 adds four methods to this same `AssistantEngine` surface and
  does the opposite: titled "The four signatures", opening "**Every annotation is
  spelled out**", and spending its length settling one argument's type and one
  method's name against the collisions they would cause.

  **What the corpus actually leaves to a lane is argument spelling, never the
  member's identity.** ADR-0073 §1 does call a `MemoryStore` signature
  illustrative, and it is a contract surface — but the method it adds is named in
  its own heading and in the block, so what the lane is handed is the keyword
  spelling of four filters, not the question of which member it is implementing.
  The draft's failure was one step worse than that: §2's clause said only that the
  store "gains **one** member: a query", naming nothing, so a lane could satisfy
  §2 and §8 with two different members and no reading of the document would catch
  it. The engine half is not exposed this way — §2's first clause fixes
  `standing_grants(self) -> tuple[SourceGrant, ...]`, that it takes no argument,
  and its two declared failures — which is why the repair is to §2's store clause
  and this block, and not to the section's form.

- **`core/types.py` gains nothing, `core/errors.py` gains nothing, and no
  `Settings` figure is owed.** `standing_grants` returns the type
  `recent_grants` already returns, its only declared failures are classes that
  exist, and a grant has no configuration (ADR-0097 §8, ADR-0102 §8).

- **ADR-0085 §5's closure is preserved and §8b's reserve is untouched.** The
  result's declared type is `tuple[SourceGrant, ...]`, whose walk terminates in
  `core` on every branch and was already walked by ADR-0102 §3.
  `standing_grants` is 15 bytes against the longest method name the surface
  carries at `25ceecb7`, `set_notification_preferences` at 28, so the envelope
  worst case and the 512-byte reserve are recomputed from the same worst case
  they already were — a worst case the notification surface set and not this
  one. ADR-0085 §8c's payload bound is applied, not changed (§2).

> **Normative.** The same change bumps `PROTOCOL_VERSION`, under ADR-0124 §9's
> third limb — "any change to the promoted surface's method set" — which that
> section states again in its own words: "Adding a method bumps, and that is the
> honest consequence rather than an oversight." Compliance is a review obligation
> on the change; #891 carries the mechanical check that does not exist.

**The contract lane**, as one change (`CONTRIBUTING.md` → "Adding a Protocol",
read as the Protocol *change* it is):

1. The two methods with their declared failures in their docstrings, and the
   `PROTOCOL_VERSION` bump. `core/types.py`'s promoted-surface comment is
   untouched: no type is added, so its "twenty-five types" stays correct. The
   `AssistantEngine` docstring's method count is governed by the clause below the
   list rather than by this item.
2. **The `AssistantEngine` conformance suite gains the clauses a store cannot
   exhibit**: `standing_grants` returns a grant whose source no held reader
   declares; it returns nothing for a revoked grant; it returns one record per
   granted source and never two; and it is unaffected by a source being present
   in or absent from `grantable_sources`. The ordering case and the oversized
   refusal below the list are required clauses rather than two of these.
3. **The `SourceGrantStore` conformance suite gains the store-side clauses**: the
   new member returns every live grant and no revoked one; it returns a detached
   snapshot, written as a mutation of the returned record's `__dict__` leaving the
   next call answering as before (ADR-0097 §10's shape); it returns a grant for a
   source `live` is never queried with; it returns an empty result on an empty
   store; and it raises `GrantError` on a store holding two live grants for one
   source, returning nothing. Input observation (ADR-0065) and cancellation
   (ADR-0060) as every seam owes.
4. **The canonical fakes gain the member and the method**, `FakeSourceGrantStore`
   and the engine fake alike, scriptable to hold live grants for sources the fake
   engine does not enumerate as grantable — so a client's own presentation of the
   disagreeing case (§1) is reachable from a test.

   Each is also scriptable into the **two-live-grants-for-one-source** state its
   own writer refuses, and the SQLite store's own tests reach it by seeding rows
   rather than through `record`.
5. **One method on `HubEngineClient`, in the same change**, a `_call` with no
   local refusal to add, because the method takes no argument. It lands with the
   Protocol because `tests/wire/test_client_contract.py` binds the client to
   `AssistantEngineContract` and a missing method is a red gate.
6. **Nothing else in `wire/` changes**, and this is recorded so the lane does not
   go looking for a table: `METHODS` is derived from the Protocol by reflection,
   arguments and results are validated from the annotations, and an error code is
   the exception class's own name resolved over `core.errors` (ADR-0102 §12).

**The list above is a lane's checklist and binds nothing; what binds is marked,
and this paragraph is the accounting ADR-0089 §4 asks a reviewer to check.**
ADR-0089 §2 puts a normative clause at column 0 and draws the consequence in as
many words — "**a normative clause cannot live inside a list item**" — and §3
makes the marks the whole of a marked ADR's obligations, with partial marking
named as the hazard. So the obligations this ADR intends are marked, and they are
marked in three places rather than gathered here:

- **The behaviour every implementation must have** is §2's: the complete live set
  or a failure, liveness from the `revokes` relation alone, meaningless ordering,
  a store-wide answer independent of what the hub holds, and `GrantError` on two
  live grants for one source. A lane that shipped the list above and none of §2
  would be refused by §2, not by the list.
- **What a client may present** is §3's four clauses; **how an amendment behaves**
  is §4's and §5's. None of them is restated here.
- **Detachment is already bound and is not re-marked**, which is why it appears in
  the list as a test rather than as a clause: ADR-0097 §4's marked clause reads
  "Every query on **either** seam returns a detached snapshot likewise", and a new
  query on that seam is a query on that seam. Re-marking it here would be this ADR
  restating a live obligation of another, which ADR-0082 §1 makes a thing to
  classify rather than a thing to do.

Three obligations are marked below because they are the ones a lane can satisfy
the letter of while leaving the clause untested, which is ADR-0097 §10's stated
criterion for lifting a case out of prose — "a test that cannot reach the code a
clause forbids is worse than no test". Each fails that way for its own reason: the
backdated revocation because every other case is about membership rather than
ordering, the oversized refusal because it bites only at a size no ordinary case
constructs, and the corrupt store because `record` makes the state unreachable
from a suite at all. Everything else stays a checklist, which is the shape
ADR-0097 §10 and ADR-0102 §12 each used for the same section under this same
regime.

> **Normative.** The contract lane restates `AssistantEngine`'s docstring method
> count as the count the Protocol then carries, rather than incrementing the
> figure written there.

**Because the figure written there is already wrong by six.** At `25ceecb7` the
Protocol carries **twenty-five** methods and the docstring says "nineteen" in two
places — ADR-0102 §12's figure, left behind by the notification and conversation
methods added since — so an increment would write a second wrong number. **The
stale figure is recorded rather than fixed here, and it is not this ADR's to
fix**: it is live text in `src/`, `CONTRIBUTING.md` → "No state claims in living
documents" is the rule it breaks, and correcting it is filed as **#1018** rather
than folded into a contract lane. What is decided here is only that the lane
touching that docstring may not perpetuate it.

> **Normative.** The `AssistantEngine` conformance suite pins §2's liveness clause
> with the case that distinguishes a stated liveness from a derived one: a grant
> revoked by a record whose `decided_at` is **earlier** than the grant's is absent
> from `standing_grants`, while `recent_grants` still returns both records.

**That case is the whole of the clause and nothing else reaches it**, for the
reason ADR-0102 §12 gave for its own: an implementation computing liveness by
walking records ordered by `decided_at` passes every other clause in the list,
because every other clause is about membership rather than about ordering.

> **Normative.** The `AssistantEngine` conformance suite pins §2's refusal over
> completion with a case that configures a frame small enough for the live set to
> exceed it: `standing_grants` raises `OversizedValueError` and returns no set,
> and the case is written against the **wire** implementation as well.

**Because refusing rather than truncating is the whole of what distinguishes this
operation, and it is the one property no other case reaches.** An implementation
that returned the store's result unmeasured — skipping the size check the engine
applies to its other operations — passes every membership, revocation and
corrupt-store case in the list, and fails only at a size an ordinary test never
constructs. ADR-0085 §8's bound and §2's clause both already forbid it; what is
missing without this case is any test that would notice. The generic oversized
coverage on the surface exercises a different method, and a bound enforced
per-method is a bound tested per-method.

> **Normative.** The canonical fakes are scriptable into the **two live grants for
> one source** state their own writers refuse, so §2's refusal is reachable from a
> test; and the SQLite store's own tests reach it by seeding rows rather than
> through `record`.

**Without it §2's refusal is a clause nothing exercises.** Every record a
conformance suite can create goes through `record`, whose atomic one-live-grant
check refuses the second — so an implementation that returned both grants would
pass the whole suite, and the surface would show two standing authorisations where
revoking one leaves the other live. This is ADR-0097 §10's requirement that its
own fakes be scriptable into a raising `live()`, applied to the second state a
writer makes unreachable.

**The store lane**: the new member on `SqliteSourceGrantStore`, as the existing
live anti-join without its source predicate, and `GrantOperations` gaining the
engine operation over it. No new database and no schema version bump: the member
reads rows the schema already holds.

**The client lane**: the standing-grants view and the amendment flow, with §3's
presentation clauses and §4's and §5's obligations as client-side tests — in
particular: an amendment whose `grant` is **known** to have failed reports that
act as failed and does not call the source ungranted without reading; an
amendment whose `grant` was refused with `InvalidGrantError` because **another
client granted the source in between** reports the source's state from the re-read
rather than from the refusal; an amendment whose `grant` outcome is **unknown** —
the hub commits the record and the client loses the response — reports it as
unknown and points at the re-read; an amendment whose **revocation** outcome is
unknown sends no grant at all; an amendment **cancelled** after the hub may have
committed either act reports that act as unknown, **starts no further call in order
to report it**, and lets the `CancelledError` propagate, written once per act; and
the granting half of an amendment renders the location before it sends (§5). Spellings are the lane's under ADR-0073 §1's form.

**Every one of those is deterministic rather than a timing test**, and it is worth
saying so because "lose the response" and "cancel mid-call" both read like flakes.
The lost-response cases drive the client against a stub hub that records the act
and then closes without answering, which is the shape `tests/wire/test_client.py`
already uses in its "what the hub refuses without answering" block. The
competing-grant case is a second engine call placed between the client's two. The
cancellation cases cancel the client's task at a point the stub controls, and
assert three things rather than one — the report, that no further call reaches the
stub after the cancellation, and that the `CancelledError` still leaves the client.
The middle one is the assertion the fifth clause's new limb needs and the stub can
already make, since it records every act it receives. What is being tested
throughout is the client's report, not the socket.

> **Normative.** This ADR's supersession record on ADR-0102 lands **in this
> change**: its `Status` line takes the partial form ADR-0070 §4 fixes, naming this
> ADR and the scope §9 states, on one physical line; and the record itself is the
> appended dated note beside it (ADR-0082 §2). The contract lane does not start
> before this pair has merged.

**The pair is atomic, and an earlier draft had it wrong.** That draft deferred the
`Status` edit to a later lane on the reading that ADR-0070 §1 permits the in-place
edit only for "recording a supersession that **has landed**", so the record could
not precede this ADR's merge. Adversarial review blocked it, correctly, and the
fence was widened by the one file (coordinator ruling, 2026-08-12). The reading was
wrong in the direction that matters: ADR-0070 §1's own gloss on "has landed" is
"This presupposes the superseding ADR *exists*" — a floor forbidding a `Superseded`
mark with no ADR behind it, not a bar on landing both in one commit, where nothing
is ever recorded ahead of its own decision because both land at the same instant.

**And the corpus had already settled it twice.** ADR-0136 §7 landed its record on
ADR-0015 in the same change, reasoning that "a merged ADR-0136 sitting beside an
unrecorded ADR-0015 is the window ADR-0082 exists to close, and ADR-0082 §7 is
explicit that an atomic pair is what makes the failure mode unreachable". ADR-0138
§7 then hit this exact case — it too deferred the record to an issue, was blocked
by adversarial review on round 2, had its fence widened by one file, and closed the
issue with the change rather than letting it outlive the decision. **#1016 closes
with this change** for the same reason. What must not happen either way is the
contract lane starting first: a lane reading ADR-0102 alone would still refuse a
fifth operation.

### 9. This ADR classified under ADR-0070 §1 and ADR-0082 §1

ADR-0082 §1 puts the judgement in the later ADR's text, where it is reviewed, and
fixes the test: *would a reader holding only the earlier ADR now act differently,
or read one of its clauses more widely than it now holds?* Applied clause by
clause.

**ADR-0102 §1 — partially superseded, and this is the whole of what is replaced.**
Its clause reads, transcribed inside a fence so that it stays ADR-0102's clause
and does not become one of this ADR's — ADR-0089 §2's own escape, since "a
`**Normative.**` line inside a fenced block is display, not a mark", and its
grammar would otherwise make a quotation of a superseded clause a live obligation
of the document superseding it:

```text
> **Normative.** The client surface for grants is exactly four methods on
> `AssistantEngine`: `grantable_sources`, `grant`, `revoke` and `recent_grants`,
> with §2's signatures. No other operation on any surface creates, revokes, or
> reports a `SourceGrant`.
```

**The escape is used rather than the quotation dropped**, because ADR-0070 §4
requires the superseding ADR to state the extent of what it replaced and an extent
stated against a paraphrase is one a reader has to trust. Adversarial review found
the unfenced form on round 2, where the scan read it as this ADR's own clause and
as a direct contradiction of §2 — which is the grammar working exactly as ADR-0089
§2 intends, on the one construction that looks most like careful citation.

**Replaced: the sentence's third limb, and the count in the sentence before it.** A
reader acting on that text builds a surface of exactly four methods and refuses a
fifth that reports a `SourceGrant`. Both are now wrong: the surface is five, and
`standing_grants` reports `SourceGrant` records. The extent is exactly that.

**Not replaced — everything else, which is nearly all of §1 and all of its
reasoning.** "No other operation on any surface **creates** … a `SourceGrant`"
stands whole, and it is the load-bearing limb: §2 above adds a *query*, and
ADR-0097 §1's "only an explicit user act creates a grant" is neither narrowed nor
touched. "**Revokes**" stands whole; `revoke` remains the only revoking operation.
§1's derivation of the count from ADR-0097 §9 stands as what it is — an account of
why *those four* exist — and every fold it tested stays refused: this ADR folds
nothing into `grant`, `revoke` or `recent_grants`, and §4 above re-refuses the
compound amendment on §1's own ground. §1's second paragraph — that a hub
operation reached by a client is an `AssistantEngine` method, because
`wire/surface.py` derives the legal set from the Protocol — is what this ADR
*follows* in adding a method rather than a side door.

**Why partial rather than whole, and why not an amendment.** ADR-0070 §3 makes the
partial form first-class and §4 fixes its shape. It is not an amendment under §1's
test, because a reader holding only ADR-0102 would refuse the fifth method: the
limb is an **exclusion**, and an exclusion that no longer holds is false rather
than merely incomplete — the distinction ADR-0101 §11 drew and ADR-0102 §13 itself
leaned on when it weighed ADR-0085 §1's "and nothing else". ADR-0102 §13 concluded
that ADR-0085's exclusion was an account of what *that* document promoted; the
same reading is not available here, because §1's exclusion is written over "any
surface" rather than over what ADR-0102 adds, and its own §14 anticipates a later
operation reporting liveness for an unheld source rather than forbidding one.

**ADR-0097 §2's two-act form — not owed.** §4 above keeps it exactly: two records,
both kept, no in-place narrowing, no compound operation. What it adds is an
obligation on a surface §2 did not write about, which is an addition beside a
ratified clause rather than a re-reading of it. A reader holding only ADR-0097
would record the same two records in the same order.

**ADR-0097 §12's read deferral — not owed, and firing it is the mechanism
working.** §6 states that the deferral's stated firing condition is met and names
what the lane owes. A deferral discharged by the route the deferral specified is
ADR-0100 §11's pattern and ADR-0083 §15's carve-out, not an amendment; ADR-0097's
sentence stays true of ADR-0097, and nothing here narrows the reasoning it gave.
The clause of §6 that could be read as reaching ADR-0097 is the one about ADR-0004
§7, and it reaches ADR-0097 not at all: ADR-0097 §4's audit claim is about granting
and revoking, and §6's third clause says so before it says what is unbuilt.

**ADR-0102 §3's `GrantableSource` — not owed.** No field is added, none is
removed, and its `live` member keeps its stated meaning and its stated
prohibition. §1 above adds a second answer beside it rather than changing what it
answers, and §2's rejection of widening `grantable_sources` is this ADR declining
to touch it.

**ADR-0102 §6's disclosure clause — not owed.** §5 above applies it to a case §6's
own words already cover — the granting half of an amendment is a `grant` — and
adds a prohibition on skipping it for a reason §6 never admitted. A reader holding
only ADR-0102 is obliged to exactly what they were obliged to before.

**ADR-0102 §14's liveness deferral — not owed.** Its firing condition is
"ADR-0093 §11's source registry, or earlier with the first deployment that removes
a reader while a grant stands and needs to say so", and this ADR fires the second.
Firing a deferral by its own condition changes no decision; §14's other deferrals
are untouched and are not re-listed.

**ADR-0094 §10's ladder deferral — not owed, and §7 is careful to leave it
standing.** §10 defers "what may cause a release" to the first capture producer
and observes that it is *probably* one decision with the grant model. §7 above
decides no rung, adds no cause, and states a precondition on that lane in the form
ADR-0097 §9a used — which ADR-0094 §10a's own marked clauses show is how this
corpus binds a deferred lane. A reader holding only ADR-0094 would take the ladder
to the same lane on the same trigger.

**ADR-0093 §7, ADR-0096 §4 and ADR-0133 §2 and §6 — not owed.** §3 above restates
each over the management surface: configuration is not a grant, no surface reports
a source's state where consent is being decided, no member of the vocabulary is
hidden, and no order over members is a rank. Restating a ratified clause over a
new surface is ADR-0097 §5's own move against ADR-0096 §4, classified there as an
addition and classified the same way here.

**ADR-0085 §1's "and nothing else" — not owed, for ADR-0102 §13's three showings
unchanged**, and this ADR adds a fourth: ADR-0102 §1 itself added four methods to
that Protocol and ADR-0102 §13 recorded no supersession of ADR-0085 for it, under
both required lenses.

**No ADR's decision text is edited by this lane, and no `VISION.md`, `CLAUDE.md`,
`CONTRIBUTING.md` or `docs/roadmap.md` is touched.** The one header edit this
decision owes — ADR-0102's `Status` line, with the dated note beside it — lands in
this change under §8's clause, and it is a header edit in ADR-0070 §1's
append-only form: no ratified sentence of ADR-0102 is rewritten, and §1's
superseded clause stays legible where it was written.

### 10. Deferred, by name, each with the condition that fires it

- **The read record itself** (§6): its store, its shape, its bound, and whether a
  refused read is recorded. Fired as a deferral and handed on as a *decision* to
  the lane §6 binds, because it needs a Protocol and golden rule 5 puts that in its
  own ADR. Its condition is met now; it is owed, bound and filed as **#1017**.
- **A grant export and a wholesale grant erasure.** ADR-0102 §14's, unchanged and
  riding on ADR-0101 §7's lane. `SourceGrantStore.export` and `clear` still reach
  no surface, and this ADR adds none: an export surface is one decision across
  every store, not one per store.
- **Reporting a standing grant's *configuration* state** — whether a held reader
  currently declares the source a standing grant names. Refused in §3 as the
  second axis arriving on the wrong surface, and refused in §2 as the
  `grantable: bool` field ADR-0102 §3 already declined. Fires with a consumer that
  needs the join and can state what it would do with it, which is not a user
  reading what they authorise.
- **A bound on `standing_grants`' result** that survives an unbounded identifier
  or an unbounded number of granted identities. ADR-0102 §14's deferral of the
  same guarantee for `revoke` and `grantable_sources` reaches this method
  unchanged, and closing it means either a length bound on a ratified `core` alias
  or a paged answer §2 refuses. Fires with the first bound on `Identifier`, or with
  ADR-0093 §11's registry.
- **Consent per act, and an assistant-initiated proposal to grant** (§7). Fires
  with the producer whose trigger needs one, under §7's third clause.
- **Everything ADR-0097 §12 and ADR-0102 §14 defer** other than the two fired
  here, unchanged and not re-listed.

## Consequences

- **Leg 11's exit test acquires its first clause.** "The user can see every source
  the assistant reads" is answerable once `standing_grants` exists: the grants
  are read from the store, so none of them can hide behind a configuration edit.
- **The surface stops having a silent state.** A live grant on a source the hub no
  longer holds was invisible and revocable — a combination in which the remedy
  existed and the user could not find it. After this it is listed, and ADR-0102
  §4's rule that `revoke` refuses nothing is what makes the listing actionable.
- **The engine surface grows by one method and the wire by nothing but a version
  bump.** Twenty-five methods become twenty-six; no promoted type is added, so
  the type count is unchanged and ADR-0085 §5's closure needs no new walk. `METHODS`, the
  adapters and the error registry are derived, so only `HubEngineClient` gains
  code — the asymmetry ADR-0102 recorded as evidence for two earlier decisions,
  holding a second time.
- **Amendment gains a shape rather than a mechanism.** The records stay two, the
  window stays open, and what changes is that a user who lands in it is told. That
  is the cheapest available fix and it is the only one that does not reopen
  ADR-0097 §2. It costs a client a third outcome to render — landed, known not to
  have landed, and not known — which is ADR-0085 §8e's residual (#570) surfacing
  where a user can act on it rather than being absorbed into a failure message.
- **A four-times-deferred debt is fired rather than re-deferred.** ADR-0097 §12's
  read record is now a lane with binding conditions and an issue, not a bullet;
  ADR-0004 §7's unbuilt half is written down as unbuilt rather than left to read as
  discharged.
- **What gets harder:** two conformance-suite obligations and two fake behaviours;
  a `PROTOCOL_VERSION` bump, which ADR-0124 §9 makes a half-finished upgrade
  legible at the cost of forcing both halves forward; and a client that offers
  amendment now owes a report for a state it could previously fail out of. All
  three are the cost of the surface being real.
- **One residual is named rather than closed.** `standing_grants` answers what is
  authorised and says nothing about what has been read, and until §6's lane lands
  there is no answer to "was this source read after I revoked it" — only ADR-0097
  §8's operator log line, which is neither durable nor exportable.
- **Revisit when** a second source exists — ADR-0093 §11's registry, which owes
  ADR-0102 §10's re-derivation and now this method's bound too — or when a capture
  producer arrives and §7's precondition binds.

## Alternatives considered

- **Widen `grantable_sources` to carry standing grants for sources no reader
  declares.** Rejected in §2: it makes the operation's name false, since ADR-0102
  §4 refuses to `grant` such a source, and it requires the `grantable: bool` field
  ADR-0102 §3 declined — reopening a ratified type to carry a state the
  enumeration's own name denies.
- **Let the client answer "what do I authorise" by walking `recent_grants` and
  applying the `revokes` relation.** Rejected in §1, and it is the rejection with
  a concrete failure rather than a principle: it is what ADR-0102 §3 forbids, and
  a revocation timestamped before its grant falls outside the page and the client
  reports a withdrawn grant as live.
- **Page `standing_grants`.** Rejected in §2. A page of what you authorise reads as
  complete while omitting an authorisation, which is the same failure in a quieter
  form; a declared `OversizedValueError` with `hub_max_frame_bytes` as the remedy
  cannot be mistaken for an empty set.
- **Compute the live set engine-side from `SourceGrantStore.export`, and add no
  store member.** Rejected in §2: the cost would grow with the store's whole
  history rather than with the number of live grants, which is ADR-0102 §10's own
  objection to an engine-side `offset` — a surface that lies about its cost.
- **Answer the enumeration for the sources a corrupted store can speak for, and
  omit the one with two live grants.** Rejected in §2: it produces a set that reads
  as complete and is not, which is the failure the no-paging clause exists to
  prevent, and it is the "proceed on the better of two answers" direction ADR-0097
  §5a refuses one query over. `SqliteSourceGrantStore.live` already raises on the
  same state rather than picking.
- **State a repair for two live grants — take the later one, or revoke both.**
  Rejected in §2 as the store editing its own history, which ADR-0097 §4 forbids in
  every other direction and which would put a write on a query path. A store that
  cannot say what the user granted says so.
- **Put the enumeration on `SourceGrants` so nothing new is added to the store
  seam.** Rejected in §2: `SourceGrants` is the driver's type, and ADR-0097 §3
  keeps it at the one member a driver is entitled to. A driver asks about the
  source it is about to read.
- **A compound `amend(source, scope)` that revokes and re-grants in one call.**
  Rejected in §4, on ADR-0097 §2's and ADR-0102 §1's grounds unchanged — two
  records, both kept — and on one more this ADR is positioned to see: a compound
  operation would hide the intermediate state inside the hub, where the client
  could not report it and the user could not be told which half landed.
- **Let a client skip the location disclosure when an amendment narrows a scope.**
  Rejected in §5. It is the one case where §6's obligation feels redundant and the
  one case where skipping it needs a scope comparison — a branch that buys nothing
  except somewhere for the mistake to live.
- **Report a last-read instant beside each standing grant, as the cheap half of
  the read record.** Rejected in §6: it is an activity claim standing where an
  authorisation claim belongs, and it would make this surface the consumer that
  justifies an unbounded store — the exact way ADR-0097 §12's refusal gets
  reversed by accident.
- **Decide #441's trigger ladder here, on ADR-0094 §10's "probably one decision".**
  Rejected in §7: the ladder's own firing condition is a capture producer, there is
  none, and deciding rungs without one is the surface-with-no-consumer refusal
  ADR-0045 §1 and ADR-0073 §4 make. The permission half is decided instead, as a
  precondition on that lane.
- **Treat a standing source grant as authorising a higher rung's trigger, so a
  capture producer needs no new consent.** Refused in §7's second clause. It is
  ADR-0133 §3's refusal on the other axis: a grant recorded before a cause existed
  says nothing about that cause, and the helpful reading is how a decision refused
  at the decision door re-enters through the implementation door.
